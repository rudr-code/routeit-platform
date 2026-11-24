# Route.it — Implementation Status & Verification Summary

## 1. Implemented Components (Complete & Verified)
- **Headless Optimization Engine (`engine/routeit_engine/`)**:
  - `contracts/types.py`: Typed immutable contracts (`SolveRequest`, `ReplanRequest`, `RunResult`, `EvaluatedPlan`, `EvaluatedRoute`, `CostLedger`, `ExactRate`, and all status/violation enums).
  - `money/ledger.py`: Exact rational paise accounting (`RoundEven` / round-half-to-even), per-route distance and time rounding, per-soft-order SLA rounding, shift activation ledger separation (`C_dec = C_inc`), and checked integer bounds (`I128_MAX` / BigInt verification).
  - `context/evaluation_context.py`: Deterministic canonical JSON serialization and SHA-256 `context_hash` including `shift_id` and `A_shift`.
  - `gatekeeper/validator.py`: Precheck input validation and sound infeasibility proofs (`d_i > Q`, homogeneous fleet lower bound `max(ceil(sum d_i / Q), count(d_i > Q/2))`, and singleton hard-window impossibility under FIFO).
  - `evaluator/canonical.py`: Sole authoritative schedule and cost evaluator supporting generalized `RouteStart` (depot start and in-transit replanning start), service completion deadline semantics (`D_i = max(A_i, a_i) + s_i <= b_i`), customer-window idle waiting (`I_idle`), and `certify_plan`.
  - `policy/vehicle_assignment.py`: Exact route-count activation marginal `G_C(m)` and `G_N(m)` sorted by `(w_k, 1[k not in A_shift], vehicle_id)`, route-limit vs. shift-ceiling enforcement, and canonical route-signature pairing.
  - `policy/comparators.py`: `CostFocused`, `Balanced` (Type-7 quantile calibration `S_C, S_I >= 1` and exact cross-product `(C_dec - C0)*S_I + (I_idle - I0)*S_C`), and `DriverProductivity` (`C_dec <= C_cap` gate before lexicographic `(N_C, N_S, N_F)` coverage, then `(I_idle, C_dec, M_shift_activated_after)`), plus shared deterministic fallback signature.
  - `split/decoder.py`: Continuation-safe Vehicle-Aware Split DP (`EXACT_TINY` and `BOUNDED_PRACTICAL` modes) with cap-safe dominance (`SPLIT-01`) and served-set tie retention (`SPLIT-02`).
  - `construct/constructors.py`, `search/ls.py`, `search/alns.py`, `search/qpso.py`: 4 constructive heuristics, deterministic Local Search (`Relocate`, `Swap`, `2-Opt`, cross-route moves), `ALNS`, `GA`, and `QPSO` (`Q-HGALS 5.0` synchronous update, `k/2^53` open-unit PRNG, linear contraction schedule, triangular-wave reflection).
  - `dynamic/replan.py`: Dynamic replanning controller with snapshot version CAS check, GPS staleness check, frozen completed orders, locked next stops, and adoption gate.
  - `adapters/solomon_and_ortools.py`: Solomon VRPTW adapter (`b'_i = b_i + s_i`) and Google OR-Tools routing adapter with capability matrix reporting.
- **Independent Reference Evaluator (`reference/routeit_reference/`)**:
  - Separate calculation path using `fractions.Fraction` for differential verification (`AC-10`).
- **Road & Traffic Services (`roads/routeit_roads/`, `traffic/routeit_traffic/`)**:
  - `EuclideanOracle` and `ProfileGraphOracle` (Strongly Connected Component validation, Ichoua-Gendreau-Potvin FIFO link traversal, arrival profile tables, and versioned cache).
  - Vadodara urban road network fixture and time-dependent traffic simulator.
- **Backend Application (`backend/app/`, `backend/migrations/`)**:
  - PostgreSQL/PostGIS DDL migration (`001_initial_schema.sql`) + zero-config SQLite transactional persistence (`database.py`) with `BEFORE UPDATE`/`BEFORE DELETE` immutability triggers on `shift_activation_ledger` and 6-step atomic CAS plan publication.
  - Complete `/v1` FastAPI endpoints (`main.py`) and worker CLI (`worker_cli.py`).
- **Dispatcher Frontend (`frontend/`)**:
  - 8-tab light-themed enterprise React + TypeScript + Vite SPA (`App.tsx`, `InteractiveMap.tsx`, `enterprise.css`).

## 2. Explicitly Deferred Post-MVP Features (`Part 11` & `Q-HGALS 5.0 §5`)
- **Driver Working-Hour / Duty-Time Limits & Mandatory Breaks (`D-01`)**: Deferred; extension hook provided in route schedule records.
- **Multiple Drivers / Co-Drivers per Vehicle (`D-02`)**: Deferred.
- **Heterogeneous Fleet Compatibility & Multi-Depot Routing (`D-03`)**: Deferred; MVP enforces homogeneous fleet interchangeability so `G_C(m)` is exact, and explicitly raises an error if heterogeneous vehicles are passed to the shortcut.
- **Live External GPS Telemetry & Live Commercial Traffic Feeds (`D-04`)**: Deferred; MVP uses deterministic simulated time-dependent traffic profiles and operational snapshots.
