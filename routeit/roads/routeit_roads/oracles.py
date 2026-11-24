"""RoadOracle implementations: EuclideanOracle and ProfileGraphOracle (Phase 5 §10 & Q-HGALS 5.0 §6.4, §6.10).

Implements:
1. `EuclideanOracle`: For synthetic tests and Solomon VRPTW benchmarks.
2. `ProfileGraphOracle`: Directed road-network graph oracle with:
   - Strongly Connected Component (SCC) validation from the depot.
   - Ichoua, Gendreau & Potvin (2003) continuous link speed integration (`traverse_edge`),
     preserving strict FIFO (`t1 <= t2 => arrival(t1) <= arrival(t2)`) by construction.
   - Closed-world arrival profile table with ceiling-second linear interpolation.
   - Explicit road closure and unreachable path detection (never falls back to straight-line distance).
   - Versioned exact road cache (`RoadCacheKey`).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import hashlib
import heapq
import json
import math
from typing import Sequence

from routeit_engine.oracle.protocol import (
    ArrivalResult,
    OracleIdentity,
    OracleStatus,
    PathGeometry,
    RoadCacheKey,
    RoadOracle,
    SnapResult,
)


@dataclass(frozen=True)
class RoadNode:
    id: str
    lon: float
    lat: float
    name: str = ""


@dataclass(frozen=True)
class RoadEdge:
    id: str
    u: str
    v: str
    length_m: int
    road_class: str = "secondary"  # "primary", "secondary", "residential", "arterial"
    free_flow_speed_mps: float = 11.11  # ~40 km/h default
    allowed_profiles: tuple[str, ...] = ("urban_van", "truck", "default")
    closed: bool = False


@dataclass(frozen=True)
class SpeedInterval:
    start_utc_s: int
    end_utc_s: int
    class_multipliers: dict[str, float]


@dataclass(frozen=True)
class TrafficScenarioSpec:
    scenario_id: str
    name: str
    revision: int
    horizon_start_utc_s: int
    horizon_end_utc_s: int
    grid_seconds: int = 900
    intervals: tuple[SpeedInterval, ...] = ()
    edge_multipliers_override: dict[str, float] = field(default_factory=dict)
    closed_edge_ids: frozenset[str] = frozenset()
    allow_boundary_clamp: bool = True

    def speed_for_edge(self, edge: RoadEdge, t_utc_s: int) -> float:
        """Return strictly positive effective speed (m/s) for edge at timestamp t_utc_s."""
        base = max(0.5, edge.free_flow_speed_mps)
        mult = 1.0
        for iv in self.intervals:
            if iv.start_utc_s <= t_utc_s < iv.end_utc_s:
                mult = iv.class_multipliers.get(edge.road_class, 1.0)
                break
        if edge.id in self.edge_multipliers_override:
            mult *= self.edge_multipliers_override[edge.id]
        return max(0.1, base * mult)

    def next_breakpoint_after(self, t_utc_s: int) -> int:
        candidates = [self.horizon_end_utc_s]
        for iv in self.intervals:
            if iv.start_utc_s > t_utc_s:
                candidates.append(iv.start_utc_s)
            if iv.end_utc_s > t_utc_s:
                candidates.append(iv.end_utc_s)
        return min(candidates)


def traverse_edge_igp(t_start: float, edge: RoadEdge, scenario: TrafficScenarioSpec) -> float:
    """Ichoua, Gendreau & Potvin (2003) piecewise-constant speed integration (Phase 5 §10.3).

    Guarantees strict FIFO monotonicity across speed interval boundaries.
    """
    if edge.length_m <= 0:
        return t_start
    remaining_m = float(edge.length_m)
    t = float(t_start)
    max_iters = 200
    for _ in range(max_iters):
        v = scenario.speed_for_edge(edge, int(math.floor(t)))
        t_next = float(scenario.next_breakpoint_after(int(math.floor(t))))
        if t_next <= t:
            return t + remaining_m / v
        reach = v * (t_next - t)
        if reach >= remaining_m - 1e-12:
            return t + remaining_m / v
        remaining_m -= reach
        t = t_next
    return t + remaining_m / scenario.speed_for_edge(edge, int(math.floor(t)))


def haversine_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> int:
    """Great-circle distance in integer meters."""
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return int(round(r * c))


class EuclideanOracle(RoadOracle):
    """Euclidean road oracle for synthetic tests and Solomon VRPTW benchmarks."""

    def __init__(
        self,
        nodes: Sequence[RoadNode],
        *,
        speed_mps: float = 1.0,
        coordinate_scale_m: float = 1.0,
        use_haversine: bool = False,
        scenario_revision: int = 0,
        unreachable_pairs: set[tuple[str, str]] | None = None,
        closed_pairs: set[tuple[str, str]] | None = None,
        horizon_start_utc_s: int = -10**9,
        horizon_end_utc_s: int = 10**12,
        speed_multipliers_by_interval: Sequence[tuple[int, int, float]] = (),
    ) -> None:
        self.nodes_by_id = {n.id: n for n in nodes}
        self.speed_mps = max(1e-6, speed_mps)
        self.coordinate_scale_m = coordinate_scale_m
        self.use_haversine = use_haversine
        self.scenario_revision = scenario_revision
        self.unreachable_pairs = unreachable_pairs or set()
        self.closed_pairs = closed_pairs or set()
        self.horizon_start_utc_s = horizon_start_utc_s
        self.horizon_end_utc_s = horizon_end_utc_s
        self.speed_multipliers_by_interval = tuple(speed_multipliers_by_interval)

        payload = {
            "nodes": [(n.id, n.lon, n.lat) for n in sorted(nodes, key=lambda x: x.id)],
            "speed_mps": self.speed_mps,
            "scale": self.coordinate_scale_m,
            "haversine": self.use_haversine,
            "unreachable": sorted(self.unreachable_pairs),
            "closed": sorted(self.closed_pairs),
            "intervals": list(self.speed_multipliers_by_interval),
        }
        self._graph_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        self._identity = OracleIdentity(
            provider_name="EuclideanOracle",
            graph_hash=self._graph_hash,
            scenario_revision=self.scenario_revision,
            model_version="EUCLIDEAN_FIFO_V1",
            grid_seconds=0,
            fifo_validated=True,
            arrival_method="EXACT_EUCLIDEAN",
            road_model="euclidean_plane",
            data_source_mode="SYNTHETIC_BENCHMARK",
        )
        self._cache: dict[RoadCacheKey, ArrivalResult] = {}

    def identity(self) -> OracleIdentity:
        return self._identity

    def snap(self, lon: float, lat: float, vehicle_profile: str = "urban_van") -> SnapResult:
        if not self.nodes_by_id:
            return SnapResult(OracleStatus.ORACLE_FAILURE, None, 0, False, "No nodes in EuclideanOracle")
        best_node = min(
            self.nodes_by_id.values(),
            key=lambda n: math.hypot(n.lon - lon, n.lat - lat),
        )
        dist = int(round(math.hypot(best_node.lon - lon, best_node.lat - lat) * self.coordinate_scale_m))
        return SnapResult(OracleStatus.OK, best_node.id, dist, True, "Snapped to Euclidean node")

    def prepare(self, node_ids: Sequence[str]) -> None:
        return None

    def _effective_travel_seconds(self, distance_m: int, departure_utc_s: int) -> int:
        if distance_m <= 0:
            return 0
        if not self.speed_multipliers_by_interval:
            return int(math.ceil(distance_m / self.speed_mps))
        # Continuous link-speed integration over intervals
        rem = float(distance_m)
        t = float(departure_utc_s)
        for _ in range(100):
            mult = 1.0
            next_bp = float(self.horizon_end_utc_s)
            for iv_start, iv_end, iv_mult in self.speed_multipliers_by_interval:
                if iv_start <= t < iv_end:
                    mult = iv_mult
                    next_bp = min(next_bp, float(iv_end))
                elif iv_start > t:
                    next_bp = min(next_bp, float(iv_start))
            v = max(0.01, self.speed_mps * mult)
            if next_bp <= t:
                t += rem / v
                break
            reach = v * (next_bp - t)
            if reach >= rem - 1e-12:
                t += rem / v
                break
            rem -= reach
            t = next_bp
        return max(0, int(math.ceil(t - departure_utc_s - 1e-9)))

    def arrival(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> ArrivalResult:
        key = RoadCacheKey(
            context_hash="",
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            departure_utc_s=departure_utc_s,
            vehicle_profile=vehicle_profile,
            graph_hash=self._graph_hash,
            scenario_revision=self.scenario_revision,
            model_version=self._identity.model_version,
        )
        if key in self._cache:
            return self._cache[key]

        if departure_utc_s < self.horizon_start_utc_s or departure_utc_s > self.horizon_end_utc_s:
            res = ArrivalResult(
                status=OracleStatus.TRAFFIC_DATA_INSUFFICIENT,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                departure_utc_s=departure_utc_s,
                arrival_utc_s=None,
                distance_m=None,
                oracle_identity=self._identity,
                message=f"Departure {departure_utc_s} outside traffic horizon [{self.horizon_start_utc_s}, {self.horizon_end_utc_s}]",
            )
            self._cache[key] = res
            return res

        if (origin_node_id, destination_node_id) in self.closed_pairs:
            res = ArrivalResult(
                status=OracleStatus.ROAD_CLOSED,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                departure_utc_s=departure_utc_s,
                arrival_utc_s=None,
                distance_m=None,
                oracle_identity=self._identity,
                message=f"Direct segment {origin_node_id}->{destination_node_id} is closed",
            )
            self._cache[key] = res
            return res

        if (
            (origin_node_id, destination_node_id) in self.unreachable_pairs
            or origin_node_id not in self.nodes_by_id
            or destination_node_id not in self.nodes_by_id
        ):
            res = ArrivalResult(
                status=OracleStatus.PATH_UNAVAILABLE,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                departure_utc_s=departure_utc_s,
                arrival_utc_s=None,
                distance_m=None,
                oracle_identity=self._identity,
                message=f"Path {origin_node_id}->{destination_node_id} unavailable",
            )
            self._cache[key] = res
            return res

        if origin_node_id == destination_node_id:
            res = ArrivalResult(
                status=OracleStatus.OK,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                departure_utc_s=departure_utc_s,
                arrival_utc_s=departure_utc_s,
                distance_m=0,
                oracle_identity=self._identity,
                path_node_ids=(origin_node_id,),
            )
            self._cache[key] = res
            return res

        u = self.nodes_by_id[origin_node_id]
        v = self.nodes_by_id[destination_node_id]
        if self.use_haversine:
            dist_m = haversine_distance_m(u.lon, u.lat, v.lon, v.lat)
        else:
            raw_d = math.hypot(u.lon - v.lon, u.lat - v.lat) * self.coordinate_scale_m
            dist_m = int(round(raw_d))

        travel_s = self._effective_travel_seconds(dist_m, departure_utc_s)
        res = ArrivalResult(
            status=OracleStatus.OK,
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            departure_utc_s=departure_utc_s,
            arrival_utc_s=departure_utc_s + travel_s,
            distance_m=dist_m,
            oracle_identity=self._identity,
            path_node_ids=(origin_node_id, destination_node_id),
            path_edge_ids=(f"{origin_node_id}->{destination_node_id}",),
        )
        self._cache[key] = res
        return res

    def path(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> PathGeometry:
        u = self.nodes_by_id[origin_node_id]
        v = self.nodes_by_id[destination_node_id]
        arr = self.arrival(origin_node_id, destination_node_id, departure_utc_s, vehicle_profile)
        return PathGeometry(
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            coordinates_lon_lat=((u.lon, u.lat), (v.lon, v.lat)),
            node_ids=(origin_node_id, destination_node_id),
            edge_ids=(f"{origin_node_id}->{destination_node_id}",),
            distance_m=arr.distance_m or 0,
        )


@dataclass
class _PairProfileEntry:
    path_node_ids: tuple[str, ...]
    path_edge_ids: tuple[str, ...]
    distance_m: int
    grid_departures_s: tuple[int, ...]
    grid_arrivals_s: tuple[int, ...]


class ProfileGraphOracle(RoadOracle):
    """Directed road-network oracle with SCC validation, FIFO link traversal, and arrival profile table (Phase 5 §10)."""

    def __init__(
        self,
        nodes: Sequence[RoadNode],
        edges: Sequence[RoadEdge],
        scenario: TrafficScenarioSpec,
        *,
        depot_node_id: str | None = None,
        max_snap_distance_m: int = 5000,
    ) -> None:
        self.nodes_by_id = {n.id: n for n in nodes}
        self.edges_by_id = {e.id: e for e in edges}
        self.scenario = scenario
        self.depot_node_id = depot_node_id or (nodes[0].id if nodes else "")
        self.max_snap_distance_m = max_snap_distance_m

        self.adj: dict[str, list[RoadEdge]] = {n.id: [] for n in nodes}
        self.rev_adj: dict[str, list[RoadEdge]] = {n.id: [] for n in nodes}
        for e in edges:
            if not e.closed and e.id not in scenario.closed_edge_ids:
                if e.u in self.adj and e.v in self.nodes_by_id:
                    self.adj[e.u].append(e)
                    self.rev_adj[e.v].append(e)

        # Compute Strongly Connected Component (SCC) containing the depot (Phase 5 §10.2)
        self.depot_scc_nodes = self._compute_depot_scc()

        payload = {
            "nodes": [(n.id, round(n.lon, 6), round(n.lat, 6)) for n in sorted(nodes, key=lambda x: x.id)],
            "edges": [
                (e.id, e.u, e.v, e.length_m, e.road_class, round(e.free_flow_speed_mps, 3), e.closed)
                for e in sorted(edges, key=lambda x: x.id)
            ],
            "closed_in_scenario": sorted(scenario.closed_edge_ids),
        }
        self._graph_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        self._identity = OracleIdentity(
            provider_name="ProfileGraphOracle",
            graph_hash=self._graph_hash,
            scenario_revision=scenario.revision,
            model_version="IGP_FIFO_PROFILE_V1",
            grid_seconds=scenario.grid_seconds,
            fifo_validated=True,
            arrival_method="INTEGRATED_SPEED_PROFILE",
            road_model="node_based_no_turn_restrictions",
            data_source_mode="SIMULATED_TIME_DEPENDENT",
        )

        self._profile_table: dict[tuple[str, str, str], _PairProfileEntry | None] = {}
        self._cache: dict[RoadCacheKey, ArrivalResult] = {}
        self.edge_to_od_pairs: dict[str, set[tuple[str, str]]] = {}

    def _compute_depot_scc(self) -> frozenset[str]:
        if self.depot_node_id not in self.nodes_by_id:
            return frozenset()

        def bfs(start: str, graph: dict[str, list[RoadEdge]], forward: bool) -> set[str]:
            visited = {start}
            q = deque([start])
            while q:
                curr = q.popleft()
                for edge in graph.get(curr, ()):
                    nxt = edge.v if forward else edge.u
                    if nxt not in visited:
                        visited.add(nxt)
                        q.append(nxt)
            return visited

        reachable_from_depot = bfs(self.depot_node_id, self.adj, forward=True)
        can_reach_depot = bfs(self.depot_node_id, self.rev_adj, forward=False)
        return frozenset(reachable_from_depot & can_reach_depot)

    def identity(self) -> OracleIdentity:
        return self._identity

    def snap(self, lon: float, lat: float, vehicle_profile: str = "urban_van") -> SnapResult:
        """Project coordinate to nearest routable node and check depot SCC membership (Phase 5 §10.2)."""
        if not self.nodes_by_id:
            return SnapResult(OracleStatus.ORACLE_FAILURE, None, 0, False, "Road network graph is empty")

        best_node: RoadNode | None = None
        best_dist = 10**12
        for node in self.nodes_by_id.values():
            d = haversine_distance_m(lon, lat, node.lon, node.lat)
            if d < best_dist:
                best_dist = d
                best_node = node

        if best_node is None or best_dist > self.max_snap_distance_m:
            return SnapResult(
                OracleStatus.PATH_UNAVAILABLE,
                best_node.id if best_node else None,
                best_dist,
                False,
                f"Nearest road node is {best_dist}m away (exceeds threshold {self.max_snap_distance_m}m)",
            )

        in_scc = best_node.id in self.depot_scc_nodes
        if not in_scc:
            return SnapResult(
                OracleStatus.PATH_UNAVAILABLE,
                best_node.id,
                best_dist,
                False,
                f"Snapped node {best_node.id} is not in the strongly connected component of depot {self.depot_node_id}",
            )

        return SnapResult(
            OracleStatus.OK,
            best_node.id,
            best_dist,
            True,
            f"Snapped to node {best_node.id} ({best_dist}m)",
        )

    def _shortest_reference_path(
        self, origin: str, destination: str, vehicle_profile: str
    ) -> tuple[tuple[str, ...], tuple[str, ...], int] | None:
        """Find fastest free-flow reference path respecting directed edges and vehicle profile."""
        if origin == destination:
            return (origin,), (), 0
        if origin not in self.nodes_by_id or destination not in self.nodes_by_id:
            return None

        pq: list[tuple[float, str]] = [(0.0, origin)]
        best_cost: dict[str, float] = {origin: 0.0}
        prev_edge: dict[str, RoadEdge] = {}

        while pq:
            cost, u = heapq.heappop(pq)
            if u == destination:
                break
            if cost > best_cost.get(u, float("inf")):
                continue
            for edge in self.adj.get(u, ()):
                if vehicle_profile not in edge.allowed_profiles and "default" not in edge.allowed_profiles:
                    continue
                edge_time = edge.length_m / max(0.5, edge.free_flow_speed_mps)
                ncost = cost + edge_time
                if ncost < best_cost.get(edge.v, float("inf")):
                    best_cost[edge.v] = ncost
                    prev_edge[edge.v] = edge
                    heapq.heappush(pq, (ncost, edge.v))

        if destination not in prev_edge:
            return None

        edges_seq: list[RoadEdge] = []
        curr = destination
        while curr != origin:
            e = prev_edge[curr]
            edges_seq.append(e)
            curr = e.u
        edges_seq.reverse()

        node_ids = [origin] + [e.v for e in edges_seq]
        edge_ids = [e.id for e in edges_seq]
        total_dist_m = sum(e.length_m for e in edges_seq)
        return tuple(node_ids), tuple(edge_ids), total_dist_m

    def traverse_path_exact(self, edge_ids: Sequence[str], departure_utc_s: int) -> int:
        """Exact composition of FIFO edge traversal functions along a path (Phase 5 §10.3)."""
        t = float(departure_utc_s)
        for eid in edge_ids:
            edge = self.edges_by_id[eid]
            t = traverse_edge_igp(t, edge, self.scenario)
        # Round up to whole seconds (D13 / U-11) so arrival is never optimistic
        return max(departure_utc_s, int(math.ceil(t - 1e-9)))

    def _build_pair_profile(
        self, u: str, v: str, vehicle_profile: str
    ) -> _PairProfileEntry | None:
        key = (u, v, vehicle_profile)
        if key in self._profile_table:
            return self._profile_table[key]

        path_info = self._shortest_reference_path(u, v, vehicle_profile)
        if path_info is None:
            self._profile_table[key] = None
            return None

        node_ids, edge_ids, dist_m = path_info
        for eid in edge_ids:
            self.edge_to_od_pairs.setdefault(eid, set()).add((u, v))

        step = max(60, self.scenario.grid_seconds)
        grid_deps: list[int] = []
        grid_arrs: list[int] = []
        t = self.scenario.horizon_start_utc_s
        prev_arr = -10**15
        while t <= self.scenario.horizon_end_utc_s:
            arr = self.traverse_path_exact(edge_ids, t)
            # Enforce monotone FIFO at grid endpoints
            if arr < prev_arr:
                arr = prev_arr
            grid_deps.append(t)
            grid_arrs.append(arr)
            prev_arr = arr
            t += step

        entry = _PairProfileEntry(
            path_node_ids=node_ids,
            path_edge_ids=edge_ids,
            distance_m=dist_m,
            grid_departures_s=tuple(grid_deps),
            grid_arrivals_s=tuple(grid_arrs),
        )
        self._profile_table[key] = entry
        return entry

    def prepare(self, node_ids: Sequence[str], vehicle_profile: str = "urban_van") -> None:
        """Precompute arrival profile table for all ordered pairs in the closed node set (Stage S3)."""
        unique_nodes = list(dict.fromkeys(node_ids))
        for u in unique_nodes:
            for v in unique_nodes:
                if u != v:
                    self._build_pair_profile(u, v, vehicle_profile)

    def arrival(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> ArrivalResult:
        cache_key = RoadCacheKey(
            context_hash="",
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            departure_utc_s=departure_utc_s,
            vehicle_profile=vehicle_profile,
            graph_hash=self._graph_hash,
            scenario_revision=self.scenario.revision,
            model_version=self._identity.model_version,
        )
        if cache_key in self._cache:
            return self._cache[cache_key]

        if (
            departure_utc_s < self.scenario.horizon_start_utc_s
            or departure_utc_s > self.scenario.horizon_end_utc_s
        ):
            if not self.scenario.allow_boundary_clamp:
                res = ArrivalResult(
                    status=OracleStatus.TRAFFIC_DATA_INSUFFICIENT,
                    origin_node_id=origin_node_id,
                    destination_node_id=destination_node_id,
                    departure_utc_s=departure_utc_s,
                    arrival_utc_s=None,
                    distance_m=None,
                    oracle_identity=self._identity,
                    message=f"Departure {departure_utc_s} out of scenario horizon",
                )
                self._cache[cache_key] = res
                return res

        if origin_node_id == destination_node_id:
            if origin_node_id not in self.nodes_by_id:
                res = ArrivalResult(
                    status=OracleStatus.PATH_UNAVAILABLE,
                    origin_node_id=origin_node_id,
                    destination_node_id=destination_node_id,
                    departure_utc_s=departure_utc_s,
                    arrival_utc_s=None,
                    distance_m=None,
                    oracle_identity=self._identity,
                    message=f"Unknown node {origin_node_id}",
                )
            else:
                res = ArrivalResult(
                    status=OracleStatus.OK,
                    origin_node_id=origin_node_id,
                    destination_node_id=destination_node_id,
                    departure_utc_s=departure_utc_s,
                    arrival_utc_s=departure_utc_s,
                    distance_m=0,
                    oracle_identity=self._identity,
                    path_node_ids=(origin_node_id,),
                )
            self._cache[cache_key] = res
            return res

        entry = self._build_pair_profile(origin_node_id, destination_node_id, vehicle_profile)
        if entry is None:
            res = ArrivalResult(
                status=OracleStatus.PATH_UNAVAILABLE,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                departure_utc_s=departure_utc_s,
                arrival_utc_s=None,
                distance_m=None,
                oracle_identity=self._identity,
                message=f"No directed road path from {origin_node_id} to {destination_node_id}",
            )
            self._cache[cache_key] = res
            return res

        deps = entry.grid_departures_s
        arrs = entry.grid_arrivals_s
        interpolated = False
        if not deps:
            arr_t = self.traverse_path_exact(entry.path_edge_ids, departure_utc_s)
        elif departure_utc_s <= deps[0]:
            travel_0 = arrs[0] - deps[0]
            arr_t = departure_utc_s + travel_0
        elif departure_utc_s >= deps[-1]:
            travel_end = arrs[-1] - deps[-1]
            arr_t = departure_utc_s + travel_end
        else:
            # Binary search on grid_departures_s
            lo = 0
            hi = len(deps) - 1
            while lo + 1 < hi:
                mid = (lo + hi) // 2
                if deps[mid] <= departure_utc_s:
                    lo = mid
                else:
                    hi = mid
            t0, t1 = deps[lo], deps[hi]
            a0, a1 = arrs[lo], arrs[hi]
            if departure_utc_s == t0:
                arr_t = a0
            elif departure_utc_s == t1:
                arr_t = a1
            else:
                interpolated = True
                # Monotone linear interpolation of arrival timestamp, ceiling to whole seconds
                num = a0 * (t1 - departure_utc_s) + a1 * (departure_utc_s - t0)
                den = t1 - t0
                arr_t = (num + den - 1) // den

        arr_t = max(departure_utc_s, arr_t)
        res = ArrivalResult(
            status=OracleStatus.OK,
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            departure_utc_s=departure_utc_s,
            arrival_utc_s=arr_t,
            distance_m=entry.distance_m,
            oracle_identity=self._identity,
            path_node_ids=entry.path_node_ids,
            path_edge_ids=entry.path_edge_ids,
            interpolated=interpolated,
        )
        self._cache[cache_key] = res
        return res

    def _street_corridor_waypoints(self, u_lon: float, u_lat: float, v_lon: float, v_lat: float) -> list[tuple[float, float]]:
        """Generate street-grid and railway-bridge-aligned intermediate waypoints for Vadodara urban legs."""
        pts: list[tuple[float, float]] = [(u_lon, u_lat)]
        RAIL_LON = 73.1784
        # Check if segment crosses the Mumbai-Delhi main railway line in Vadodara urban area
        in_vadodara = (22.22 <= u_lat <= 22.38 and 22.22 <= v_lat <= 22.38 and 73.10 <= u_lon <= 73.26 and 73.10 <= v_lon <= 73.26)
        crosses_rail = in_vadodara and ((u_lon - RAIL_LON) * (v_lon - RAIL_LON) < -1e-7)
        if crosses_rail:
            mid_lat = 0.5 * (u_lat + v_lat)
            if mid_lat >= 22.328:
                bridge_w, bridge_e = (73.1745, 22.3338), (73.1795, 22.3342)  # Chhani / Nizampura Overbridge
            elif mid_lat >= 22.313:
                bridge_w, bridge_e = (73.1762, 22.3154), (73.1806, 22.3158)  # Shastri Flyover Bridge
            elif mid_lat >= 22.301:
                bridge_w, bridge_e = (73.1758, 22.3094), (73.1802, 22.3087)  # Alkapuri RC Dutt Underpass
            elif mid_lat >= 22.282:
                bridge_w, bridge_e = (73.1735, 22.2948), (73.1815, 22.2954)  # Akota-Dandia Bazaar Flyover
            else:
                bridge_w, bridge_e = (73.1795, 22.2755), (73.1865, 22.2748)  # Manjalpur Overbridge
            if u_lon < v_lon:
                pts.extend([(u_lon, bridge_w[1]), bridge_w, bridge_e, (v_lon, bridge_e[1])])
            else:
                pts.extend([(u_lon, bridge_e[1]), bridge_e, bridge_w, (v_lon, bridge_w[1])])
        elif in_vadodara and (abs(u_lon - v_lon) > 0.004 and abs(u_lat - v_lat) > 0.004):
            # Follow arterial street grid (two smooth intermediate corners instead of cutting diagonally across blocks)
            mid_lon = round(u_lon + 0.55 * (v_lon - u_lon), 5)
            pts.append((mid_lon, round(u_lat + 0.15 * (v_lat - u_lat), 5)))
            pts.append((mid_lon, round(u_lat + 0.85 * (v_lat - u_lat), 5)))
        pts.append((v_lon, v_lat))
        return pts

    def path(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> PathGeometry:
        entry = self._build_pair_profile(origin_node_id, destination_node_id, vehicle_profile)
        if entry is None:
            return PathGeometry(
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
                coordinates_lon_lat=(),
                node_ids=(),
                edge_ids=(),
                distance_m=0,
            )
        coords_list: list[tuple[float, float]] = []
        node_seq = [nid for nid in entry.path_node_ids if nid in self.nodes_by_id]
        if len(node_seq) == 1:
            n0 = self.nodes_by_id[node_seq[0]]
            coords_list.append((n0.lon, n0.lat))
        else:
            for u_id, v_id in zip(node_seq, node_seq[1:]):
                nu, nv = self.nodes_by_id[u_id], self.nodes_by_id[v_id]
                seg_pts = self._street_corridor_waypoints(nu.lon, nu.lat, nv.lon, nv.lat)
                for pt in seg_pts:
                    if not coords_list or coords_list[-1] != pt:
                        coords_list.append(pt)
        return PathGeometry(
            origin_node_id=origin_node_id,
            destination_node_id=destination_node_id,
            coordinates_lon_lat=tuple(coords_list),
            node_ids=entry.path_node_ids,
            edge_ids=entry.path_edge_ids,
            distance_m=entry.distance_m,
        )
