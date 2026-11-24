# Route.it — Render Deployment Guide (render.com)

This guide provides end-to-end instructions for deploying the **Route.it Intelligent Fleet Routing & Optimization Platform (Q-HGALS 5.0)** on **Render** (https://render.com).

---

## Architecture Overview

Route.it is packaged as a **Unified Full-Stack Service**:
- **Frontend**: React 18 + TypeScript + Vite Dispatcher UI + MapLibre GL
- **Backend**: FastAPI REST API (`/v1`) + Q-HGALS 5.0 TD-CVRPTW Engine + Road Oracle + Traffic Simulator
- **Database**: Automatic zero-config transactional SQLite with foreign keys & shift ledger immutability triggers (or Render Managed PostgreSQL)
- **Deployment Model**: A single multi-stage container that builds the frontend SPA and serves both the REST API and the web application under a single URL. This eliminates CORS misconfiguration, avoids cross-origin cold-start failures, and fits 100% within Render's free tier.

```
       Internet / User Browser
                  │
                  ▼
   https://<your-app>.onrender.com
                  │
  ┌───────────────┴─────────────────┐
  │         FastAPI App             │
  │  ├─ /          --> React Vite UI│
  │  ├─ /assets/*  --> UI Static JS │
  │  ├─ /v1/*      --> REST API     │
  │  ├─ /docs      --> OpenAPI Docs │
  │  └─ /healthz   --> Health Check │
  └─────────────────────────────────┘
```

---

## Method 1: 1-Click Render Blueprint Deployment (Recommended)

Render Blueprints use the included `render.yaml` infrastructure-as-code specification.

### Step 1: Initialize Git and Push to GitHub

If you have not already pushed your code to GitHub or GitLab:

```bash
# In the project root directory
git init
git add .
git commit -m "feat: complete Route.it platform with Render production configuration"

# Create a new repository on GitHub and push (using GitHub CLI or web)
gh repo create routeit-platform --public --source=. --push
# OR using standard git:
# git remote add origin https://github.com/<your-username>/routeit-platform.git
# git branch -M main
# git push -u origin main
```

### Step 2: Deploy on Render

1. Open [Render Dashboard](https://dashboard.render.com).
2. Click **"New +"** in the top right and select **"Blueprint"**.
3. Connect your GitHub / GitLab account and select your `routeit-platform` repository.
4. Render will automatically detect `render.yaml` and display the `routeit-platform` web service.
5. Click **"Apply"**.
6. Render will automatically:
   - Build the React SPA frontend with Node 20.
   - Install Python 3.11 and all optimization dependencies.
   - Run health checks against `/v1/healthz`.
   - Provide your live public URL (e.g., `https://routeit-platform-xxxx.onrender.com`).

---

## Method 2: Manual Web Service Deployment (Docker)

If you prefer to configure the Web Service manually via Render's dashboard:

1. Go to [dashboard.render.com](https://dashboard.render.com) -> **"New +"** -> **"Web Service"**.
2. Select your repository.
3. Configure settings:
   - **Name**: `routeit-platform`
   - **Region**: Choose the closest region (e.g. `Oregon (US West)` or `Frankfurt (EU)`)
   - **Language / Runtime**: `Docker`
   - **Dockerfile Path**: `./Dockerfile`
   - **Instance Type**: `Free` (or `Starter` for higher CPU)
4. Under **"Environment Variables"**, verify or add:
   - `ROUTEIT_ENV` = `production`
   - `ROUTEIT_SQLITE_PATH` = `/app/data/routeit.db`
5. Under **"Health Check Path"**, set:
   - `/v1/healthz`
6. Click **"Create Web Service"**.

---

## Method 3: Manual Web Service Deployment (Native Python + Node)

If you prefer using Render's native build environment instead of Docker:

1. Go to [dashboard.render.com](https://dashboard.render.com) -> **"New +"** -> **"Web Service"**.
2. Select your repository.
3. Configure settings:
   - **Runtime**: `Python 3`
   - **Build Command**: `./render-build.sh`
   - **Start Command**: `./render-start.sh`
   - **Instance Type**: `Free`
4. Set Environment Variables:
   - `ROUTEIT_ENV` = `production`
   - `ROUTEIT_SQLITE_PATH` = `./data/routeit.db`
   - `PYTHONPATH` = `routeit/engine:routeit/reference:routeit/roads:routeit/traffic:routeit/backend`
5. Click **"Create Web Service"**.

---

## Database Configuration

### 1. Default (SQLite — Zero Config)
Route.it includes a self-initializing, transactional SQLite database with:
- Foreign key constraints
- Immutable `shift_activation_ledger` triggers
- Atomic compare-and-swap (CAS) plan publication

SQLite runs automatically inside the service without needing any external database configuration.

### 2. Production PostgreSQL + PostGIS (Optional)
If you require a persistent external PostgreSQL database on Render:
1. In the Render Dashboard, click **"New +"** -> **"PostgreSQL"**.
2. Name it `routeit-db`, and choose the Free or Starter tier.
3. Copy the **Internal Database URL** from the database settings.
4. In your Route.it Web Service settings, add the environment variable:
   - `ROUTEIT_POSTGRES_DSN` = `postgresql://user:pass@host/routeit`
5. Apply the initial schema:
   ```bash
   psql "$ROUTEIT_POSTGRES_DSN" -f routeit/backend/migrations/001_initial_schema.sql
   ```

---

## Verifying Your Live Deployment

Once Render finishes deploying:

1. **Check Health Endpoint**:
   Visit `https://<your-service>.onrender.com/v1/healthz`
   Expected response:
   ```json
   {
     "status": "ok",
     "service": "routeit-api",
     "engine_version": "Q-HGALS-5.0-REV-2026-11-16",
     "road_network_nodes": 60,
     "road_network_edges": 142
   }
   ```

2. **Open the Dispatcher Web App**:
   Visit `https://<your-service>.onrender.com` in your browser.
   - Click **"Load Vadodara Pilot Scenario"** in the top action bar to immediately populate depot, delivery orders, vehicles, cost profiles, and traffic scenarios.
   - Run an optimization job with **Q-HGALS 5.0 (QPSO / ALNS)**.
   - View live road network routes, driver dispatch portals, customer tracking views, and the immutable shift activation ledger.

3. **Explore OpenAPI Documentation**:
   Visit `https://<your-service>.onrender.com/docs` to interactively inspect and test all 30+ REST endpoints.
