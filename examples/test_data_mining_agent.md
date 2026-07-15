# CONTEXT.md — Test Data Mining Agent (canonical context)

> **Single source of truth.** This is the one document to read before working on this project —
> for humans and AI agents alike. It describes *what the agent is, how it works, and the rules that
> must not be broken.*

---

## 1. What this is

An agent that **generates accurate, ready-to-use test data**. A QA engineer uploads **test cases /
user stories** (what fields are needed) plus, optionally, their **JUnit / Playwright result files**
(what was actually tested + real values). The agent mines existing data from **MongoDB** and similar
data from **ChromaDB**, detects **coverage gaps**, then **generates new, coherent rows** — offering
the analyst candidate value sets per field at a human-in-the-loop gate. The result is **rows of test
data**: the original uploaded rows (verbatim) **plus** newly generated rows, downloadable as a clean
**CSV**, with optional save-back to the stores for reuse.

- **Agent ID:** `test-data-mining`
- **Type:** L2 multi-node LangGraph `StateGraph` (gather -> generate -> review -> synthesise -> persist)
- **Autonomy:** L2 only — the set-selection review gate **always runs**. The only other human
  decision is the explicit save gate in `persist`.
- **Language/stack:** Python 3.11+ · LangGraph · FastAPI · React + Vite + Tailwind · MongoDB ·
  ChromaDB · `sentence-transformers` (all-MiniLM-L6-v2) · Google Gemini (optional LLM seam).

### The two inputs
| Input | Role | Formats |
|---|---|---|
| **Primary — test cases / user stories** | the field list to generate for | `.xlsx`, `.csv`, `.json`, `.txt` (Gherkin) |
| **Supporting — test results** | coverage-gap detection + realistic seed values | JUnit/TestNG `.xml`, Playwright `.json` |

### The output
The final dataset is **all original rows (untouched) + newly generated rows appended**, always with
**more rows out than in**, in **exactly the uploaded columns**. Each output row carries a UI-only
**provenance** tag — `input` / `generated` / `fetched` / `gathered` — which is shown on screen but
**never written to the CSV**.

---

## 2. Invariants — DO NOT VIOLATE

These are hard rules. Code that breaks one is a bug.

1. **Read-before-write on MongoDB.** The entire mine phase is read-only. The only write is the
   explicit `persist` gate, and only when the analyst sets `save=true`.
2. **No graph database. No Neo4j.** Vectors -> **ChromaDB**; documents -> **MongoDB**.
3. **Deterministic before LLM.** `parse`, `load_results`, `mongo_lookup`, `vector_search`,
   `coverage_gap` are pure/deterministic and run **before** any LLM step.
4. **Graceful degradation.** Any store unreachable or input malformed -> empty result + a `gaps`
   note, **never crash**. No data at all -> still generate (pure-LLM / deterministic fallback).
5. **Schema-agnostic — never hardcode column names or per-domain rules.** The output columns are
   exactly the uploaded file's columns. Relationships are **learned from the uploaded data at
   runtime**, never written into the code.
6. **Additive, never subtractive.** Output = original rows (verbatim) + new rows. Never delete,
   dedupe, reformat, clean, or "optimize" the originals.
7. **Always >= input (relaxed rule).** `output_rows >= input_rows`, every run — aim for ~2x (a soft
   target), never "too few", no hard cap, never fail for "too many".
8. **Coherent whole rows.** New rows are generated as *whole records* (never index-zipped columns),
   so cross-field relationships hold.
9. **Unique ids.** Id-like columns get freshly minted ids continuing the observed pattern; a
   generated/fetched/gathered row never reuses an existing id. The primary key is **never nulled**.
10. **Provenance is UI-only.** `source` rides alongside rows in the API (`output_rows`); the
    exported CSV (`final_dataset`) is clean — original columns only.
11. **LLM via the seam, with a deterministic fallback.** Any LLM use goes through `llm.py`
    `get_llm()` (Google Gemini, key from env `GEMINI_API_KEY`, never committed). No key / no quota
    -> deterministic generation, so everything runs offline and in tests.
12. **Embeddings are local + offline.** `all-MiniLM-L6-v2` (384-dim) loaded from a local snapshot
    via `embedding.py`; if the model/stack can't load it falls back to a deterministic hashed
    embedder. No network at runtime.

> **Status note (current):** the LangGraph graph wires nodes as bare functions, so the graph path
> runs **deterministic** (llm=None). The Gemini seam is built and tested but not activated
> graph-wide — turning it on is a deliberate, separate toggle.

---

## 3. Pipeline & topology

```
parse -> load_results -> mongo_lookup -> vector_search -> coverage_gap
      -> generate -> review (HITL, ALWAYS) -> synthesise -> persist
```

Wired **sequentially** (single-parent chain), not parallel. `review` always interrupts
via `interrupt()` -> `Command(resume=...)`. `persist` writes only when its gate is `save=true`.

| Node | Type | Responsibility |
|---|---|---|
| `parse` | deterministic | Primary inputs -> `parsed_fields` + `input_rows` (verbatim) + `input_columns` |
| `load_results` | deterministic | JUnit/Playwright -> `result_signals` + `seed_values` (passing runs) |
| `mongo_lookup` | deterministic | MongoDB existing data -> `existing_data` (**fetched**) |
| `vector_search` | vector (ChromaDB) | MiniLM similarity -> `retrieved_data` (**gathered**) |
| `coverage_gap` | deterministic | `fields x {valid,boundary,negative,edge}` minus exercised -> `coverage_gaps` |
| `generate` | LLM seam | Per field: 2-3 candidate value **sets** (valid / gap-filling), constraint-validated |
| `review` | HITL (always) | Pause; analyst picks one set per field (or excludes); resume |
| `synthesise` | det. + LLM seam | **Output = input_rows + coherent generated + fetched + gathered**; provenance + unique ids |
| `persist` | deterministic (gated) | If `save=true`: write dataset to MongoDB + upsert ChromaDB |

---

## 4. How generation works (the heart)

**Grounded.** Generation is grounded on real data: the LLM (or the offline fallback) sees the
uploaded example rows **plus** known real values per column merged from the analyst's picks +
**fetched** (MongoDB) + **gathered** (ChromaDB). Empty stores reduce grounding but never block.

**Coherent (two paths, both schema-agnostic):**
- **LLM path** (`synthesise._llm_rows`): prompt with the exact columns + real example rows; the model
  infers types and inter-column relationships and emits fresh whole rows per scenario.
- **Offline fallback** (`synthesise._perturb`): clone a real row, perturb only what the scenario
  needs. Coherence comes from the cloned real row, not from rules.

**Data-driven inference** (`inference.py`, zero domain knowledge): classifies each column by content,
detects id patterns and mints unique ids, measures fill-rate, and learns categorical correlations
statistically. Nothing here references a specific column name.

**Iterative loop:** `POST /generate-more` takes the rows the analyst picked, makes them the new base,
increments `round_index`, and regenerates everything else grounded on them (**replace** semantics).

---

## 5. Stores, embeddings, LLM

- **MongoDB** (documents) — existing datasets. Live via `MONGODB_URI`, else a local JSON seed in
  `data/sample_mongo/`.
- **ChromaDB** (vectors) — similar datasets, embedded from a descriptive context. Local persistent
  store at `data/sample_chroma/` (`CHROMA_PATH`).
- **Embeddings** — `all-MiniLM-L6-v2` (384-dim) via `sentence-transformers`, loaded **offline** from
  a local snapshot. Deterministic hashed embedder is the automatic fallback. Similarity threshold
  tuned to **0.40** (`CHROMA_THRESHOLD`).
- **LLM** — Google Gemini via `google-genai`, `llm.py` `get_llm()`, key from env `GEMINI_API_KEY`,
  model `GEMINI_MODEL` (default `gemini-2.5-flash`). No key -> deterministic fallback.

---

## 6. API surface (FastAPI — `backend/app.py`)

| Endpoint | Purpose |
|---|---|
| `POST /mine` | upload `test_cases[]` (+ optional `results[]`) or pasted `text`; streams NDJSON node events to the review `interrupt` |
| `POST /resume` | `session` + `review_selections` JSON -> streams to the `result` (report + `final_dataset` + `output_rows`) |
| `POST /generate-more` | `session` + `seed_selection` -> a fresh grounded round seeded by the picked rows |
| `POST /persist` | `session` + `save` + `label` + `tags` -> write the latest dataset to MongoDB + ChromaDB |
| `GET /health` | liveness |

---

## 7. Where everything lives

```
test-data-mining-agent/
  CLAUDE.md · README.md · requirements.txt
  docs/  CONTEXT.md (this file) · ARCHITECTURE.md · DATA-FLOW.md · BACKEND.md · UNDERSTANDING.md
  src/test_data_mining/
    state.py · graph.py · llm.py · embedding.py · inference.py
    nodes/  parse · load_results · mongo_lookup · vector_search · coverage_gap · generate · review · synthesise · persist
  backend/app.py   # FastAPI: /mine /resume /generate-more /persist /health
  frontend/src/    # React+Tailwind: InputPanel · TracePanel · ReviewGate · ReportView · PersistGate
  scripts/ · data/ · tests/  # 57 tests
```

---

## 8. Commands

```bash
pip install -r requirements.txt
python scripts/generate_fixtures.py
python scripts/check_embedding_offline.py
pytest -q                                       # 57 tests
python -m test_data_mining.graph --input data/sample_upload
uvicorn backend.app:app --port 8000
```

Env (gitignored `.env`): `GEMINI_API_KEY`, `GEMINI_MODEL`, `SSL_CERT_FILE`, `EMBED_MODEL_PATH`,
`MONGODB_URI`, `CHROMA_PATH`, `CHROMA_THRESHOLD`. None are required — the agent runs fully offline.

---

## 9. Tests (57, all passing)

Per-node units + integration + adversarial + backend + v3 suites (additive/schema-agnostic,
coherence, provenance, iterative loop, offline embeddings, full-graph universality).

---

## 10. Conventions

- Every node is a pure function `def node(state, llm=None) -> dict` returning only the keys it updates.
- Structured log prefixes: `NODE_ENTER` / `NODE_EXIT`, `EMBED_MODEL` / `EMBED_FALLBACK`, `WS_EVENT`,
  `LLM_CALL` / `LLM_RESP`, `NODE_ERROR`.
- Checkpointer: `MemorySaver` (required for `interrupt()`/resume).
- Never commit secrets; `.env` and `.certs/` are gitignored.
