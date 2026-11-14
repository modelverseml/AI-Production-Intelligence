# AI Production Incident Intelligence Platform

An agentic AIOps platform that finds the root cause of production incidents in microservice systems. An LLM agent (Azure OpenAI, orchestrated with LangGraph) investigates telemetry through tools, uses a trained LightGBM ranker as a prior, cites the evidence behind every claim, and has those citations verified before its report is accepted. The system is evaluated on **RCAEval**, a public benchmark of faults injected into real microservice systems.

**Stack:** LangGraph · Azure OpenAI (tool calling, structured outputs) · LightGBM LambdaRank · scikit-learn · hybrid RAG (BM25 + sentence-transformers + RRF) · FastAPI · PostgreSQL · SQLAlchemy · JWT/RBAC (Argon2) · React + Vite

## Results

All numbers come from `backend/rcaeval_evaluation.json` and `backend/ranker_evaluation.json`, produced by the scripts in this repo.

**Held-out comparison: 250 RCAEval cases** (all 270 cases minus the 20 used for prompt development; LLM `gpt-5.4` on Azure OpenAI)

| Method | Top-1 (AC@1) | Top-3 (AC@3) | Avg@5 |
|---|---|---|---|
| Statistical baseline (BARO-style) | 58.4% | 89.6% | 0.840 |
| LightGBM ranker (root-cause service held out) | 86.4% | **96.8%** | 0.949 |
| LLM agent only | 88.8% | 96.4% | 0.958 |
| LLM agent + ML ranker (hybrid) | **92.0%** | **96.8%** | **0.966** |

**Agent quality and cost** (hybrid / agent only, same 250 cases)

| Measure | Hybrid | Agent only |
|---|---|---|
| Citations verified against tool outputs | 100% | 100% |
| Reports that needed the verifier's correction loop | 1 (0.4%) | 2 (0.8%) |
| Mean tool calls per investigation | 17.3 | 20.6 |
| Cost per investigation (estimate) | $0.047 | $0.050 |
| Latency p50 / p95 | 16 s / 58 s | 18 s / 80 s |
| Fault-type accuracy (secondary task) | 57.6% | 60.4% |

**ML ranker on all 270 cases**

| Protocol | AC@1 | Avg@5 |
|---|---|---|
| Statistical baseline | 57.4% | 0.835 |
| Case-split CV (optimistic, shown for transparency) | 95.2% | 0.983 |
| Root-cause service held out (headline) | **86.3%** | **0.950** |
| Whole application held out | 81.5% | 0.933 |

**What the results say**
- Every learned method beats the statistical baseline by roughly 28–34 points of top-1 accuracy.
- The hybrid agent is the most accurate method: 92.0% top-1, against 86.4% for the ML ranker alone and 88.8% for the agent without the ML prior. The prior also makes investigations cheaper (fewer tool calls and tokens).
- The agent's value is explainability with guarantees: every report names suspects, explains why, cites evidence, and suggests a fix. All 500 reports cite only evidence that a tool actually returned; the verifier sent 3 back for correction.
- Classifying the fault type (CPU, memory, delay, code defect, …) is the weakest part at about 58–60%. Code-level faults often look like resource problems in the telemetry.


## Architecture

```
React ── incidents · agent report + trace · benchmarks · user admin
  │
FastAPI ── JWT · RBAC (viewer / analyst / admin) · Pydantic
  │
  ├── LLM investigation agent (LangGraph)
  │     START → ml_prior → agent ⇄ tools → verify → END
  │                          ↑                 │
  │                          └── rejected ─────┘  (cited an ID no tool returned)
  │
  │     tools: list_services · get_top_anomalies · get_service_metrics · get_service_logs ·
  │            get_service_traces · get_dependencies · search_runbooks (hybrid RAG)
  │
  ├── Telemetry feature extraction (pandas / numpy)
  │     robust z-scores before vs. after the alert · log-template novelty and
  │     error rates · trace error/latency shifts · call graph from spans
  │
  └── LightGBM LambdaRank root-cause ranker
  │
PostgreSQL ── users · services · incidents · runbooks · investigations (report, trace, tokens, cost)
```

### How an investigation works

1. **Evidence extraction.** Each case is split at the alert time. Every metric gets a robust z-score of its post-alert values against the pre-alert distribution. Logs are reduced to templates (numbers, IDs and timestamps masked), and the extractor measures the error-keyword rate and *never-seen-before* templates. Traces give per-service error rate and p90 latency shifts, and the call graph comes from parent/child spans. Every piece of evidence gets a stable ID such as `MET:carts_cpu`, `LOG:carts:new` or `TRC:carts:latency`.
2. **ML prior (hybrid mode).** A LightGBM LambdaRank model scores every candidate service. Its out-of-fold ranking is handed to the agent as a prior.
3. **Agent loop.** The LLM chooses which tools to call: it inspects candidates, follows dependencies to separate the origin of a fault from its downstream symptoms, and searches the runbook library.
4. **Structured report.** `submit_report` uses a strict JSON schema: ranked services with likelihoods, rationales and evidence IDs, plus the fault type, summary, remediation and runbook IDs.
5. **Citation verification.** The `verify` node rejects any report that cites an evidence or runbook ID no tool actually returned, or a service that doesn't exist. The errors go back to the agent so it can correct itself (up to 2 retries). Every report records its verification result, token usage, cost and full tool trace.

## Evaluation methodology

- **Benchmark.** [RCAEval](https://arxiv.org/abs/2412.17015) (Pham et al., 2025): RE2-OB, RE2-SS, RE3-OB, RE3-SS and RE3-TT, 270 cases in total. The cases come from Online Boutique, Sock Shop and Train Ticket, with CPU, memory, disk, socket, network-delay, packet-loss and code-level faults. Labels come from the benchmark, never from this project.
- **Metrics.** AC@k is the share of cases whose true root-cause service is ranked in the top k. Avg@5 is the mean of AC@1 through AC@5. These are the standard RCA metrics.
- **No leakage into the ranker.** Cross-validation folds are grouped by *root-cause service*, so every test case's faulty service was never a root cause during training. A case-split CV scores higher (0.95 AC@1), but it is optimistic and reported only for transparency. Leave-one-system-out tests generalization to an unseen system. Structural features (call-graph degree, "is a database") were tried and dropped because they let the model memorize which services the benchmark tends to break.
- **No leakage into the agent.** Case folder names encode the label, so the agent only receives anonymous telemetry and an alert message. The ML prior it gets is the out-of-fold ranking.
- **Held-out prompt evaluation.** Prompts were developed on 20 pilot cases (`results/dev_cases.json`), and those cases are excluded from the reported LLM results.
- **Comparable sets.** Every method is scored on the same cases. All LLM runs are cached in `results/rcaeval_runs/*.jsonl` (report, trace, tokens, cost), so the numbers can be audited.

## Setup

Requirements: Python 3.12+, PostgreSQL 15+, Node 20+, and an Azure OpenAI deployment (results above use `gpt-5.4`).

### 1. Database

```bash
createuser ai_agent_user --pwprompt
createdb ai_intelligence_db -O ai_agent_user
psql -d ai_intelligence_db -c "ALTER SCHEMA public OWNER TO ai_agent_user;"   # PostgreSQL 15+
```

### 2. Backend

```bash
cd backend
source ~/Documents/Projects/venvs/ai-intelligent-agent/bin/activate   # or your own venv
pip install -r requirements.txt
cp .env.example .env            # DB URL, JWT secret, admin login, Azure OpenAI settings

python -m scripts.seed          # runbook library + admin user (--reset drops all tables)
python -m scripts.download_rcaeval   # ~1.3 GB from Hugging Face
python -m scripts.train_ranker       # features, CV, out-of-fold rankings, model
python -m scripts.import_rcaeval     # benchmark cases → incidents
uvicorn app.main:app --reload
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev                     # http://localhost:5173
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, open a benchmark incident, choose *LLM agent + ML ranker* or *LLM agent only*, and run the analysis. The **Benchmarks** page shows the evaluation results.

### 4. Evaluate

```bash
cd backend
python -m scripts.train_ranker                 # ranker_evaluation.json
python -m scripts.evaluate_rcaeval --per-dataset 0   # all held-out cases -> rcaeval_evaluation.json (resumable)
python -m scripts.evaluate_rcaeval --per-dataset 4 --include-dev   # quick pilot -> rcaeval_pilot.json (git-ignored)
```

Azure deployments are rate-limited by tokens per minute. The agent backs off on 429 responses and caps output tokens, because Azure reserves prompt + max output tokens against the quota for every request.

## API

| Method | Path | Role |
|---|---|---|
| POST | `/api/auth/register` | public (creates viewer) |
| POST | `/api/auth/login` | public |
| GET | `/api/auth/me` | any |
| GET | `/api/services` · `/api/incidents` · `/api/incidents/{id}` · `/api/incidents/{id}/telemetry` · `/api/stats` | any |
| GET | `/api/investigations/{incident_id}` | any |
| POST | `/api/investigations/{incident_id}?mode=hybrid\|agent` | analyst, admin |
| GET | `/api/evaluations` | any |
| GET | `/api/users` · PATCH `/api/users/{id}/role` | admin |

## Project layout

```
backend/app/
  telemetry.py     evidence extraction from metrics, logs and traces; BARO-style baseline
  ranker.py        LightGBM LambdaRank features, model loading, out-of-fold lookup
  agent.py         LangGraph agent: ML prior, tool loop, strict report schema, citation verification
  llm.py           Azure OpenAI client (v1 API) and cost estimates
  rca_metrics.py   AC@k / Avg@5
  retrieval.py     hybrid RAG over runbooks: BM25 + embeddings + RRF + rerank
  routes.py · security.py · models.py · schemas.py · config.py · database.py · main.py
backend/scripts/
  download_rcaeval.py · train_ranker.py · import_rcaeval.py · evaluate_rcaeval.py
  seed.py (runbooks + admin)
frontend/src/
  pages/           Login · Dashboard · Incident · Benchmarks · Users
  components/      AgentReport (ranked candidates, citations, trace, cost) · Layout · EvidenceList
```

## Limitations

- RCAEval faults are injected in testbeds, and each case has exactly one faulty service. Real incidents are messier.
- RE3-TT has only two distinct root-cause services, so per-dataset numbers on 26–30 cases have wide confidence intervals.
- Cost figures are estimates from list prices and the token counts Azure returns.
