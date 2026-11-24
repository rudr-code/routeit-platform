# Route.it — Project Master Plan

## 1. Mission & Engineering Scope
Route.it is an intelligent time-dependent fleet-routing and delivery optimization platform solving the **Time-Dependent Capacitated Vehicle Routing Problem with Time Windows (TD-CVRPTW)**.

This repository implements the complete vertical stack defined across the three authoritative source specifications:
1. **Route.it Project Master Document (v2.0, 15 Nov 2026)** — Problem understanding, MVP scope, operational constraints, unified monetary objective, acceptance criteria (`AC-01` through `AC-13`).
2. **Route.it Phase 5 System Architecture & Technical Engineering Design (v0.2, 16 Nov 2026)** — Modular monolith architecture, headless engine boundary, database schema, Addendum A shift activation ledger, API contracts, RoadOracle design, and dynamic replanning pipeline.
3. **Q-HGALS 5.0 Revised Mathematical and Engineering Specification (16 Nov 2026)** — Normative mathematical formulation, exact route-count activation marginal `G_C(m)` and `G_N(m)`, deterministic vehicle identity assignment, Driver Productivity comparator hierarchy, integer-paise rational accounting (`RoundEven`), continuation-safe Split DP (`EXACT_TINY` and `BOUNDED_PRACTICAL`), synchronous QPSO update contract, and 50+ mathematical acceptance fixtures (`ACT-01..13`, `SPLIT-01..03`, `CMP-01..10`, `IDLE-01..02`, `PROF-01..02`, `QPSO-01..06`, `ROAD-01`, `MNY-01..09`, `EVAL-01..05`, `DYN-01..04`).

## 2. Document Authority Hierarchy
1. **Q-HGALS 5.0 (16 Nov 2026)**: Governs all optimization mathematics, schedule simulation, monetary rounding, vehicle identity assignment, profile comparators, Split DP dominance, and QPSO/GA/ALNS/LS solver semantics.
2. **Phase 5 System Architecture v0.2 (16 Nov 2026, including Addendum A)**: Governs module boundaries, dependency rules, database entities, `shift_activation_ledger`, atomic plan publication, API contracts, and job lifecycle.
3. **Master Document v2.0 (15 Nov 2026)**: Governs product scope, domain workflows, dispatcher UX, and acceptance criteria (`AC-01..AC-13`).

## 3. Staged Implementation Roadmap
- **Stage 0**: Repository inspection, specification reconciliation, traceability mapping, and decision register (`PROJECT_MASTER_PLAN.md`, `DECISION_REGISTER.md`, `ARCHITECTURE_TRACEABILITY.md`, `SHARED_CONTRACTS.md`).
- **Stage 1**: Project foundation, packaging (`pyproject.toml`, `package.json`, `docker-compose.yml`, `.env.example`), and automated test runner.
- **Stage 2**: Engine contracts (`SolveRequest`, `ReplanRequest`, `RunResult`, `Plan`, `Route`), immutable `EvaluationContext` & SHA-256 context hashing, `money/ledger.py` exact rational arithmetic & `RoundEven`, `gatekeeper` sound prechecks, canonical evaluator (`evaluator/step.py`), and independent reference evaluator (`routeit_reference`).
- **Stage 3**: `RoadOracle` protocol, `EuclideanOracle` (Solomon & synthetic benchmarks), `ProfileGraphOracle` (directed road graph, strongly connected component validation, Ichoua-Gendreau-Potvin integrated-speed FIFO traversal, arrival profile tables), and `routeit_traffic` scenario builder & execution simulator.
- **Stage 4**: Baseline solvers (4 deterministic/seeded constructors: Cost-Greedy, Idle-Aware, Regret-2, Randomized-Feasible), `VehicleAwareSplit` decoder (`EXACT_TINY` and `BOUNDED_PRACTICAL` modes with `G_C(m)`/`G_N(m)` and deterministic vehicle matching), and deterministic Local Search (`relocate`, `swap`, `2-opt`, `Or-opt`).
- **Stage 5**: Advanced metaheuristics — `ALNS`, `GA` (Order Crossover + mutation), `QPSO` / `Q-HGALS 5.0` (exact synchronous update, `k/2^53` open-unit RNG mapping, linear contraction schedule, triangular-wave reflection, Baldwinian/Archive memory), OR-Tools benchmark adapter, and benchmarking suite.
- **Stage 6**: Backend application (`backend/app`), relational persistence (PostgreSQL/PostGIS DDL migrations + zero-config SQLite/SQLAlchemy operational engine for local/test execution), immutable `shift_activation_ledger`, atomic compare-and-swap plan publication, process-based job queue worker, and REST API endpoints (`/v1/...`).
- **Stage 7**: Dispatcher SPA (`frontend/`), enterprise light-themed SaaS UI, interactive map (`MapLibre GL JS` + local vector/canvas fallback when Mapbox credentials are absent), progressive disclosure planning wizard, real-time run monitor, route/timeline/cost breakdown inspector, and dynamic replanning console.
- **Stage 8–10**: End-to-end integration, full automated test execution across all mathematical and system fixtures, benchmark runs, and verified ZIP packaging.
