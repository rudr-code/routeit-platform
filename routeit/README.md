# Route.it — Intelligent Time-Dependent Fleet Routing & Optimization Platform (`Q-HGALS 5.0`)

Route.it is an end-to-end transportation and logistics optimization platform solving the **Time-Dependent Capacitated Vehicle Routing Problem with Time Windows (TD-CVRPTW)**.

It implements the complete specification from:
1. **Route.it Project Master Document (v2.0, 15 Nov 2026)**
2. **Route.it Phase 5 System Architecture & Technical Engineering Design (v0.2, 16 Nov 2026, including Addendum A)**
3. **Q-HGALS 5.0 Revised Mathematical and Engineering Specification (16 Nov 2026)**

---

## 1. Repository Structure

```text
routeit/
├─ PROJECT_MASTER_PLAN.md          # Master engineering plan & authority hierarchy
├─ DECISION_REGISTER.md            # Cross-document conflict resolutions & reversible defaults
├─ ARCHITECTURE_TRACEABILITY.md    # AC-01..AC-13 & 54 mathematical fixtures traceability
├─ SHARED_CONTRACTS.md             # Canonical units, data models & REST API contracts
├─ IMPLEMENTATION_STATUS.md        # Implemented vs. explicitly deferred features
├─ CHANGELOG.md                    # Staged engineering log
├─ pyproject.toml                  # Python workspace package configuration
├─ .env.example                    # Environment configuration template (zero secrets)
├─ engine/                         # Headless optimization library (routeit_engine, zero web/DB imports)
│  ├─ routeit_engine/
│  │  ├─ contracts/                # Typed immutable data contracts & status enums
│  │  ├─ money/                    # Exact rational rates, checked ints & RoundEven ledger
│  │  ├─ context/                  # Canonical JSON serialization & SHA-256 context_hash
│  │  ├─ oracle/                   # RoadOracle protocol & versioned RoadCacheKey
│  │  ├─ gatekeeper/               # Input validation & sound precheck infeasibility proofs
│  │  ├─ evaluator/                # Authoritative schedule simulator & CostLedger evaluator
│  │  ├─ policy/                   # Vehicle identity assignment G_C(m)/G_N(m) & PlanComparator
│  │  ├─ split/                    # Continuation-safe Vehicle-Aware Split DP (EXACT_TINY & BOUNDED)
│  │  ├─ construct/                # 4 deterministic/seeded constructive heuristics
│  │  ├─ search/                   # Local Search, ALNS, GA, and QPSO (Q-HGALS 5.0)
│  │  ├─ dynamic/                  # Dynamic replanning controller & Adoption Gate
│  │  ├─ adapters/                 # Solomon VRPTW & Google OR-Tools routing adapters
│  │  └─ orchestrator.py           # Top-level solve(), replan(), and certify() entry points
│  └─ tests/                       # 54 mathematical acceptance fixtures & solver/profile tests
├─ reference/                      # Independent Fraction-based reference evaluator (AC-10)
├─ roads/                          # EuclideanOracle, ProfileGraphOracle (IGP FIFO + SCC), Vadodara graph
├─ traffic/                        # Time-dependent traffic scenario & operational snapshot simulator
├─ backend/                        # FastAPI /v1 application, SQLite/PostgreSQL persistence & shift ledger
│  ├─ app/
│  ├─ migrations/                  # 001_initial_schema.sql (PostgreSQL + PostGIS + ledger triggers)
│  └─ tests/                       # CRUD, T-ACT-5..11 ledger immutability/CAS/idempotency & E2E tests
├─ benchmarks/                     # Reproducible multi-solver benchmark runner & executed reports
├─ frontend/                       # React + TypeScript + Vite light-themed Enterprise Dispatcher SPA
│  ├─ src/
│  └─ tests/                       # Automated Node.js frontend verification suite
└─ infra/                          # Docker Compose, Dockerfile.backend, Dockerfile.frontend
```

---

## 2. Software Requirements & Dependencies

- **Python**: `>= 3.11`
  - Core packages: `fastapi`, `pydantic`, `uvicorn`, `httpx`, `numpy`
  - Optional benchmark adapter: `ortools`
- **Node.js**: `>= 18.0` (with `npm`)
- **Database**:
  - **Local / Zero-Config Default**: Built-in transactional `sqlite3` with foreign-key enforcement, `BEFORE UPDATE`/`BEFORE DELETE` immutability triggers on `shift_activation_ledger`, and `BEGIN IMMEDIATE` atomic compare-and-swap plan publication.
  - **Production Container Deployment**: `PostgreSQL 15+` with `PostGIS 3.4+` (`backend/migrations/001_initial_schema.sql`).

---

## 3. Environment & Database Setup Instructions

1. **Copy the environment template**:
   ```bash
   cp .env.example .env
   ```
2. **Database initialization**:
   - **Local SQLite mode (automatic)**: When starting the backend (`ROUTEIT_SQLITE_PATH=./data/routeit.db`), the schema and `shift_activation_ledger` immutability triggers are automatically initialized on startup.
   - **PostgreSQL + PostGIS mode**:
     ```bash
     psql "$ROUTEIT_POSTGRES_DSN" -f backend/migrations/001_initial_schema.sql
     ```

---

## 4. Running the Complete Platform

### Option A: Local Development (Backend + Frontend)

1. **Start the FastAPI Backend Server (Port 8000)**:
   ```bash
   PYTHONPATH=engine:reference:roads:traffic:backend uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
2. **Start the React + Vite Dispatcher Frontend (Port 5173)**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. Open `http://localhost:5173` in your browser. Click **"Load Vadodara Pilot Scenario"** in the top bar (or create your own depot, vehicles, and orders) and run an optimization job.

### Option B: Docker Compose Full-Stack Deployment

```bash
cd infra
docker compose up --build
```

---

## 5. Executing the Automated Test Suites & Benchmarks

1. **Run the Q-HGALS 5.0 Mathematical, Solver & Differential Evaluator Test Suite (`engine/tests`)**:
   ```bash
   PYTHONPATH=engine:reference:roads:traffic python3 -m unittest discover -s engine/tests -v
   ```
2. **Run the Backend API, Shift Activation Ledger (`T-ACT-5..11`), and End-to-End Integration Suite (`backend/tests`)**:
   ```bash
   PYTHONPATH=engine:reference:roads:traffic:backend python3 -m unittest discover -s backend/tests -v
   ```
3. **Run the Frontend Verification Test Suite (`frontend/tests`)**:
   ```bash
   node frontend/tests/frontend_verification.test.mjs
   ```
4. **Run the Multi-Solver Benchmark Suite (`benchmarks/run_benchmarks.py`)**:
   ```bash
   PYTHONPATH=engine:reference:roads:traffic python3 benchmarks/run_benchmarks.py
   ```
   Outputs are written to `benchmarks/results/benchmark_report.json` and `benchmarks/results/BENCHMARK_REPORT.md`.

---

## 6. Known Limitations & Deferred Scope

- **Homogeneous Fleet Shortcut (`G_C(m)`)**: As specified in Q-HGALS 5.0 §2.1, the route-count activation marginal `G_C(m)` requires homogeneous vehicle capacity and profile across eligible vehicles. Passing heterogeneous vehicle capacities or profiles raises an explicit validation error rather than silently applying an invalid shortcut.
- **Node-Based Directed Graph**: `ProfileGraphOracle` enforces directed edges, one-way street restrictions, and depot Strongly Connected Component (SCC) reachability, and reports `road_model = "node_based_no_turn_restrictions"`.
- **Deferred Features (`Part 11`)**: Driver hours-of-service (HOS) and mandatory break scheduling, multi-driver handovers, pickup-and-delivery, multi-depot routing, and live external GPS/traffic feeds are deferred beyond the MVP.
