"""RoadOracle protocol and versioned cache keys (Q-HGALS 5.0 §6.4, §6.10 & Phase 5 §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence


class OracleStatus(str, Enum):
    OK = "OK"
    PATH_UNAVAILABLE = "PATH_UNAVAILABLE"
    ROAD_CLOSED = "ROAD_CLOSED"
    UNSUPPORTED_RESTRICTION = "UNSUPPORTED_RESTRICTION"
    TRAFFIC_DATA_INSUFFICIENT = "TRAFFIC_DATA_INSUFFICIENT"
    ORACLE_FAILURE = "ORACLE_FAILURE"


@dataclass(frozen=True)
class OracleIdentity:
    provider_name: str
    graph_hash: str
    scenario_revision: int
    model_version: str
    grid_seconds: int
    fifo_validated: bool = True
    arrival_method: str = "INTEGRATED_SPEED_PROFILE"
    road_model: str = "node_based_no_turn_restrictions"
    data_source_mode: str = "SIMULATED_TIME_DEPENDENT"

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "graph_hash": self.graph_hash,
            "scenario_revision": self.scenario_revision,
            "model_version": self.model_version,
            "grid_seconds": self.grid_seconds,
            "fifo_validated": self.fifo_validated,
            "arrival_method": self.arrival_method,
            "road_model": self.road_model,
            "data_source_mode": self.data_source_mode,
        }


@dataclass(frozen=True)
class SnapResult:
    status: OracleStatus
    snapped_node_id: str | None
    snap_distance_m: int
    in_depot_scc: bool
    message: str = ""


@dataclass(frozen=True)
class ArrivalResult:
    status: OracleStatus
    origin_node_id: str
    destination_node_id: str
    departure_utc_s: int
    arrival_utc_s: int | None
    distance_m: int | None
    oracle_identity: OracleIdentity
    path_node_ids: tuple[str, ...] = ()
    path_edge_ids: tuple[str, ...] = ()
    interpolated: bool = False
    fifo_corrected: bool = False
    message: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.status == OracleStatus.OK
            and self.arrival_utc_s is not None
            and self.distance_m is not None
            and self.arrival_utc_s >= self.departure_utc_s
            and self.distance_m >= 0
        )

    @property
    def travel_seconds(self) -> int:
        if not self.ok or self.arrival_utc_s is None:
            raise ValueError("Cannot read travel_seconds from failed ArrivalResult")
        return self.arrival_utc_s - self.departure_utc_s


@dataclass(frozen=True)
class PathGeometry:
    origin_node_id: str
    destination_node_id: str
    coordinates_lon_lat: tuple[tuple[float, float], ...]
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    distance_m: int


@dataclass(frozen=True)
class RoadCacheKey:
    """Exact road cache key per Q-HGALS 5.0 §6.10."""

    context_hash: str
    origin_node_id: str
    destination_node_id: str
    departure_utc_s: int
    vehicle_profile: str
    graph_hash: str
    scenario_revision: int
    model_version: str


class RoadOracle(Protocol):
    """Protocol for road-level routing behind the fleet optimizer."""

    def identity(self) -> OracleIdentity:
        ...

    def snap(self, lon: float, lat: float, vehicle_profile: str = "urban_van") -> SnapResult:
        ...

    def prepare(self, node_ids: Sequence[str]) -> None:
        ...

    def arrival(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> ArrivalResult:
        ...

    def path(
        self,
        origin_node_id: str,
        destination_node_id: str,
        departure_utc_s: int,
        vehicle_profile: str = "urban_van",
    ) -> PathGeometry:
        ...
