# CX Sentinel AI

**Autonomous Customer Experience Intelligence & Recovery Platform** — TCS AI Engineering Hackathon, Challenge 06.

> Detecting unhappy customers is the easy part. CX Sentinel investigates **why** they are unhappy, coordinates the
> right business response, and **verifies** that the experience actually recovered.

```
SIGNAL → ISSUE → SEGMENT → ROOT CAUSE → IMPACT → INTERVENTION → EXECUTION → VERIFICATION
```

Every demo record is **simulated** (clearly labelled in the UI, the API and the sample files). No real customer data is used.

---

## What it does

| | |
|---|---|
| **8 specialised agents** orchestrated by **LangGraph** | Signal Intelligence · Emerging Issue Detection · Customer Segmentation · Root Cause Investigation · Business Impact · Intervention Planning · Recovery Execution · Verification & Learning |
| **Real statistics, not prompts** | HDBSCAN clustering on text embeddings, Poisson / two-proportion baselines, binomial change-point onset, Fisher exact + Benjamini–Hochberg segmentation, Mantel–Haenszel confounder-adjusted effects |
| **Evidence traceability** | Every hypothesis claim is stored with its inputs and is *recomputed from the data* by an evidence validator (point-in-time replay), surfaced as a groundedness score |
| **Correlation ≠ causation** | Confidence is capped below certainty; each hypothesis carries supporting *and* contradicting evidence, alternatives, missing data and a causal-claim statement |
| **Human approval** | Consequential actions wait in the Approval Center; execution uses simulated enterprise tools with retries, idempotency keys, failure logging and compensating rollback |
| **Verification, not assumption** | Executing an action never counts as recovery. KPIs of post-intervention cohorts are tested against the pre-intervention cohort; failure re-opens the investigation and down-weights the failed cause |
| **Dynamic jury simulator** | Inject surprise evidence (another city, congestion, a new data feed, conflicting reports, adversarial text). The data really flows through ingestion; the agents recompute and the UI shows *original vs updated* investigation |
| **Evaluation Center** | Precision / recall, root-cause accuracy, groundedness, segmentation recall, false-positive rate, acceptance, latency, cost and recovery against a hidden benchmark |

## Architecture

```mermaid
flowchart LR
  subgraph UI[React + TypeScript + Tailwind]
    P[Overview · Signals · Issues · Root Cause · Impact · Interventions · Approvals · Monitoring · Simulator · Evaluation]
  end
  subgraph API[FastAPI]
    R[REST + WebSocket<br/>JWT · RBAC · audit]
    O{{LangGraph supervisor}}
  end
  subgraph AG[Agents]
    A1[1 Signal] --> A2[2 Issue detection] --> A3[3 Segmentation] --> A4[4 Root cause]
    A4 --> V[Evidence validator] --> A5[5 Impact] --> A6[6 Planning]
    A6 -. human approval .-> A7[7 Execution] --> A8[8 Verification]
    A8 -. failed? re-open .-> A4
  end
  DB[(MySQL / SQLite<br/>28 tables, Alembic)]
  subgraph SIM[Simulated enterprise]
    T[ITSM · notification gateway · finance ERP · ops control plane]
    W[World model: hidden causal factors]
  end
  UI <--> R --> O --> AG
  AG <--> DB
  A7 --> T --> W
  W -- new data as revisions --> DB
```

The supervisor inspects the persisted investigation state (issue, hypotheses, interventions, approvals) and routes to the
next agent; evidence validation can loop back to root-cause analysis with a wider look-back; each agent is retried once on
failure; a pending approval ends the run in `awaiting_approval` and approving resumes the graph. Every step is written to
`agent_execution_history` (agent, task, input evidence, reasoning *summary*, output, status, timestamp).

### Honest separation of concerns

* **Agents** only read the normalised evidence store. They never import the simulator and never read the benchmark ground truth (enforced by a test).
* **Simulated world** (`server/app/sim`) generates the data and reacts to executed actions. Hidden causal factors decide whether a fix really works.
* **Late-arriving data**: when time advances or new evidence is injected, changed records are ingested as *new revisions* of existing records (history is never overwritten).

## Technology

| Layer | Choice |
|---|---|
| Frontend | React 19, Vite, TypeScript, Tailwind CSS 4, React Router, Axios, TanStack Query, Recharts, React Flow (evidence graph), Lucide |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PyJWT + bcrypt, WebSockets, background tasks |
| Database | **MySQL 8** (PyMySQL). Automatic SQLite fallback in development so the demo always starts |
| AI / analytics | LangGraph, scikit-learn (HDBSCAN clustering, TF-IDF/SVD embeddings, IsolationForest multivariate anomaly cross-check), pandas, NumPy, SciPy, NetworkX, VADER sentiment, keyword-lexicon aspect extraction |
| Optional upgrades | `server/requirements-ml.txt`: sentence-transformers MiniLM embeddings, spaCy, ruptures (auto-detected, never required) |
| LLM (optional) | OpenRouter / any OpenAI-compatible endpoint through env vars. Works fully offline with `LLM_PROVIDER=none` |

Notes on the stack: the analytics layer follows the recommended stack (VADER, HDBSCAN, MiniLM, NetworkX, OpenRouter). Where the
challenge brief differs (React instead of Streamlit, MySQL instead of SQLite) the brief wins; React Flow replaces PyVis and
Recharts replaces Plotly.

## Quick start

### Option A — Docker (MySQL + API + UI)

```bash
cp .env.example .env          # set MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD and SECRET_KEY
docker compose up --build
```

UI → <http://localhost:8080> · API docs (Swagger) → <http://localhost:8000/api/docs>

### Option B — Local development

```powershell
# 1. backend
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt      # Linux/macOS: .venv/bin/python
cd ..
copy .env.example .env                                         # edit DATABASE_URL (see below)
cd server
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. frontend (new terminal)
cd client
npm install
npm run dev                                                    # http://localhost:5173
```

**MySQL**: create the database and user, then put the URL in `.env`.

```sql
CREATE DATABASE cx_sentinel CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cx_user'@'%' IDENTIFIED BY 'cx_password';
GRANT ALL ON cx_sentinel.* TO 'cx_user'@'%';
```
```
DATABASE_URL=mysql+pymysql://cx_user:cx_password@localhost:3306/cx_sentinel?charset=utf8mb4
```
Migrations run automatically on start (`AUTO_MIGRATE=true`) or manually with `cd server && python -m alembic upgrade head`.
If MySQL is unreachable and `DB_FALLBACK_SQLITE=true`, the app logs a warning and uses `server/data/cx_sentinel.db`.

**Demo accounts** (password = `DEMO_PASSWORD`, default `CxSentinel#2026`): `admin@`, `analyst@`, `approver@`, `viewer@` `cxsentinel.ai`.

| Role | Can |
|---|---|
| viewer | read everything |
| analyst | + upload data, run analyses, jury simulator, submit approvals |
| approver | + approve / reject / execute / roll back, read audit log |
| admin | + reset demo, retention purge, manage users |

First start loads the simulated datasets, runs the full analysis in the background (≈10 s) and the dashboards fill in. Set
`SEED_DEMO_DATA=false` to start empty and upload files yourself.

## Jury walkthrough (maps to the acceptance test)

| # | Step | Where |
|---|---|---|
| 1 | Upload multiple datasets (or *Load sample datasets*) | **Signal Explorer → Upload & validate** (dry-run preview, validation errors, idempotent ingest) |
| 2–3 | Detect an emerging issue and cluster related complaints | **Issue Intelligence → Run detection** |
| 4 | Identify impacted segments | **Root Cause → Impacted segments**, **Customer Impact** |
| 5–6 | Competing hypotheses with supporting *and* contradicting evidence; interactive evidence graph | **Root Cause** |
| 7 | Business impact with formulas, assumptions, ranges | **Customer Impact** (expand a metric) |
| 8–9 | Compare interventions, submit for approval | **Intervention Center** → **Approval Center** |
| 10 | Execute the approved simulated action | automatic after *Approve & execute* (retry visible in the intervention log) |
| 11–12 | Introduce unexpected evidence; re-investigate; compare old vs new | **Jury Simulator → Surprise evidence** |
| 13–14 | Monitor real simulated KPI change; verify improvement | **Recovery Monitoring → Advance & verify** |
| 15 | Entire decision and execution history | **Execution History**, investigation *Timeline* / *Agent decisions* |

What you should see with the shipped data: the delivery issue's top hypothesis is *“SwiftShip onboarded in Mumbai”* (≈83 %);
after the surprise evidence it falls to ≈55 % while *traffic congestion* rises to ≈77 %, the warehouse hypothesis is refuted
by the newly connected metric and the recommended action switches from partner reassignment to congestion-aware routing.
Advancing the simulated clock then verifies the (already executed) partner reassignment as **not recovered** and re-opens the investigation.

## Data

`server/data/samples/*.csv` (generated deterministically by `app/sim`, **simulated**): 3,087 transactions, ~580 reviews, ~250 social posts,
~320 tickets, ~130 surveys, 207 telemetry rows, 390 operational metrics, 106 operational events, 22 releases, 1,500 pseudonymous customers,
5 customer segments and 30 days of KPI history. Five scenarios (delivery delays, payment failures, app crashes, product quality, refund delays),
two decoys (a price-complaint blip and a one-day social burst) and three adversarial “prompt-injection” reviews.

Ground truth lives in `server/data/benchmark/ground_truth.json` and is read only by the evaluation service. Regenerate everything with
`cd server && python -c "from datetime import datetime; from app.services import seed; seed.generate_samples(datetime(2026,10,31))"`.

## API

Swagger UI: `/api/docs` · ReDoc: `/api/redoc` · OpenAPI: `/api/openapi.json`. Highlights:

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/users` |
| Data | `POST /api/data/upload`, `POST /api/signals/ingest`, `GET /api/signals`, `GET /api/signals/semantic`, `POST /api/data/load-samples` |
| Detection | `POST /api/issues/detect`, `GET /api/issues`, `GET /api/clusters`, `POST /api/pipeline/run` |
| Investigation | `POST /api/investigations/{id}/run`, `GET /api/investigations/{id}`, `GET …/graph`, `POST /api/issues/{id}/{segmentation,root-cause,impact,interventions/plan}` |
| Actions | `GET /api/interventions`, `POST …/submit`, `GET /api/approvals`, `POST /api/approvals/{id}/{approve,reject}`, `POST …/execute`, `POST …/rollback` |
| Recovery | `GET /api/monitoring/overview`, `POST /api/monitoring/advance`, `POST /api/monitoring/verify/{issue_id}` |
| Simulator | `GET /api/scenarios/schema`, `POST /api/scenarios/run`, `GET /api/scenarios/{id}` |
| Evaluation | `GET /api/evaluation` |
| System | `GET /api/health`, `GET /api/history`, `GET /api/audit-logs`, `POST /api/system/retention/purge`, WebSocket `/api/ws?token=` |

## Security and responsible AI

* JWT authentication, bcrypt password hashing, role-based least-privilege dependencies, login throttling, audit trail for every state change.
* Secrets only from environment variables (`.env.example` documents all); no keys in code.
* **Prompt-injection defence**: customer text is treated as data. Instruction-like spans are removed, flagged and excluded from analytics; PII (email, phone, card, ID) is masked before storage. Customer text can never reach a tool call — tools are invoked only from approved intervention records.
* **LLM output validation**: optional explanations must only contain numbers and evidence IDs present in the supplied facts, otherwise the deterministic explanation is used.
* **Privacy & fairness**: pseudonymous customers, k-anonymity floor (groups < 10 suppressed), allow-listed non-protected segmentation dimensions, remediation is targeted by *experienced failure*, not demographics.
* Human approval for consequential actions; retries, idempotency, failure logging and rollback for execution; data-retention purge for admins.
* Observed facts, inferred hypotheses and predicted outcomes are visibly separated (Observed / Inferred / Predicted badges; Measured / Estimated impact labels).

## Tests

```bash
cd server && python -m pytest          # 30 tests: stats, guardrails, API acceptance workflow, execution/rollback, migrations
cd client && npm run typecheck && npm run build
```

The API test-suite drives the full acceptance workflow (upload → detection → hypotheses → approval → execution → injected evidence →
re-investigation → verification failure → re-opened investigation → evaluation).

## Project layout

```
client/                React + TypeScript UI (src/pages = the ten modules)
server/app/agents/     the 8 agents, LangGraph orchestrator, LLM client, evidence validator
server/app/analytics/  statistics and data frames
server/app/services/   ingestion, NLP, KPIs, scenarios, evaluation, graph, approvals
server/app/tools/      simulated enterprise systems (tools with compensation)
server/app/sim/        simulated world + hidden ground truth (not used by agents)
server/app/api/        REST routers      server/alembic/  migrations      server/tests/  test-suite
```

## Verification status

* Backend: 30/30 tests pass on SQLite; the browser UI was exercised end to end in headless Chromium (login, every module, approval → execution, simulator, advance & verify).
* MySQL: all 28 tables compile for the MySQL dialect and the Alembic migration is dialect-aware, but the application was **not** run against a live MySQL server in the build environment (credentials were not available there) — please run it once against yours.
* Docker files are provided but were not executed in the build environment (Docker was not installed).
* Estimates (revenue at risk, churn uplift, unit costs) rely on documented, configurable assumptions — they are shown as such in the UI.
