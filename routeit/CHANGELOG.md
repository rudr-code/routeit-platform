# Route.it — Engineering Changelog

## v5.0.0 (2026-11-17)
- **Stage 0 & 1**: Established monorepo layout, reconciled all conflicts across Master Document v2.0, Phase 5 Architecture v0.2 (including Addendum A), and Q-HGALS 5.0 Revised Specification (`DECISION_REGISTER.md`, `ARCHITECTURE_TRACEABILITY.md`, `SHARED_CONTRACTS.md`).
- **Stage 2**: Implemented `routeit_engine` contracts, exact rational paise accounting (`RoundEven`), SHA-256 `EvaluationContext`, `Gatekeeper` sound prechecks, `CanonicalEvaluator`, `SortedVehiclePool` (`G_C(m)`, `G_N(m)`), `PlanComparator` & Type-7 quantile calibration, and independent `routeit_reference` evaluator.
- **Stage 3**: Implemented `EuclideanOracle`, `ProfileGraphOracle` (with depot Strongly Connected Component check and Ichoua-Gendreau-Potvin FIFO speed integration), and `routeit_traffic` incident/snapshot simulator.
- **Stage 4 & 5**: Implemented Constructive portfolio, continuation-safe `VehicleAwareSplit` (`EXACT_TINY` and `BOUNDED_PRACTICAL`), deterministic Local Search, `ALNS`, `GA`, `QPSO` (`Q-HGALS 5.0`), Solomon VRPTW adapter, and Google OR-Tools adapter.
- **Stage 6**: Implemented FastAPI backend (`/v1`), PostgreSQL/PostGIS schema migration (`001_initial_schema.sql`), transactional SQLite persistence with immutable `shift_activation_ledger` triggers, and 6-step atomic CAS plan publication.
- **Stage 7**: Built 8-tab light-themed enterprise React + TypeScript + Vite Dispatcher SPA with interactive road-network map, location confirmation workflow, progressive disclosure optimization wizard, cost ledger inspector, dynamic replanning console, and benchmark view.
- **Stage 8–10**: Executed all mathematical, differential, backend, frontend, and benchmark suites and packaged the complete repository.
