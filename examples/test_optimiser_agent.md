# Test Optimiser Agent

> **Framework:** LangGraph · **Autonomy Level:** L3 · Goal-driven

---

## 1. What It Does

- Your test suite grows over time and becomes slow, messy, and untrustworthy — this agent cleans it up
- Looks at every test, scores it, and decides: is this test actually doing its job?
- Flags tests that are duplicated, randomly failing, too slow, or testing code that no longer exists
- Finds parts of your code that have no tests at all and writes new ones to fill those gaps
- Won't let coverage drop below your set limit no matter what it removes
- Stops and asks a human before doing anything that can't be undone

---

## 2. Autonomy — L3

- **L1** — you script every step
- **L2** — you give a task, it finds the steps
- **L3** — you give a goal, it finds the tasks and steps
- **L4** — sets its own goals

**Why L3:** You say "suite under 10 mins, above 80% coverage" — agent figures out how to get there, adapts to what data shows, but cannot do anything destructive without human sign-off

**Why not L2:** Diagnosing the problem IS what the agent does — you can't give it a specific task when you don't know what the task is yet

**Why not L4:** One wrong autonomous call on a test suite has real production consequences — agent owns the *how*, humans own the *what* and the *whether*

**Autonomy growth over time:**

| Stage | Trust earned | Unattended capability |
|-------|--------------|------------------------|
| 1 — Assistive | Day one | Recommends only |
| 2 — Semi-autonomous | Proven accurate per project | Auto-quarantines flaky tests (reversible) |
| 3 — Goal-autonomous | Sustained reliability | Auto-merges duplicates, auto-tiers suite |

- Destructive deletes stay human-gated permanently
- Autonomy expands on measured correction rate, not time elapsed

---

## 3. Inputs

- **Test suite** — the tests you already have, required to start
- **Project** — which codebase these tests belong to, required
- **Optimization goal** — what problem are you solving: speed, coverage, reliability, or cost
- **Coverage target** — the minimum % of code that must stay tested, defaults to 80%
- **Risk areas** — parts of the codebase that are sensitive, agent treads carefully here
- **Additional context** — anything extra the agent should know about your project

---

## 4. Outputs

- **Test Health Scorecard** — report card for your entire suite, scored across every dimension
- **Coverage & Gap Map** — shows exactly what's tested and what's a blind spot, sorted by how dangerous each gap is
- **Redundancy & Flakiness Report** — every problematic test called out with the evidence behind it
- **Optimised Test Plan** — every single test gets a verdict: keep it, merge it, quarantine it, or move it to a different tier
- **Generated Test Cases** — brand new tests written by the agent to plug the gaps it found
- **Context Sources** — everything the agent used to reach its conclusions, so you can verify its reasoning

---

## 5. Triggers

- **Manual** — you open it, paste your suite in, run it yourself when you want
- **API** — another system calls it automatically, no human clicks anything
- **Webhook** — it listens for events in your pipeline and fires on its own when:
  - Someone pushes new code
  - A pipeline fails
  - New requirements get added
- *Implementation status:* **Manual** (CLI `main.py` + the React UI) and **API** (FastAPI `api.py` -> `POST /runs`, `POST /runs/{id}/resume`, `GET /runs/{id}`, `/health`) are built; the **Webhook** trigger is planned (Phase 11)

---

## 6. Hardware

- Runs on normal cloud servers, nothing special needed
- The AI models themselves run elsewhere via API — not on this machine
- Needs to reach three things: your code repo, your CI system, and your past test run history
- One special piece: an isolated container where generated tests are run safely before touching anything real

---

## 7. Software Stack

- **LangGraph** — the traffic controller that runs the whole pipeline, handles pauses, loops, and decision points
- **LLM — Google Gemini** — used when real thinking is needed: explaining scores, writing test code, making prioritisation calls. Reached through one client (`src/llm.py`). Two configurable slots — `REASONING_MODEL` (judgement) and `FAST_MODEL` (lighter passes) — both **default to `gemini-2.5-flash`**, so the same model fills both today; `FAST_MODEL` can be pointed at a cheaper tier later
- **Deterministic fallback (no LLM)** — every LLM call is optional. With no `GEMINI_API_KEY`, in `OFFLINE_MODE`, or on a provider error/quota (429), scoring falls back to a deterministic rubric and gap generation to convention-matching stubs — the run always completes, with the degrade recorded in `tool_errors`
- **Vector store** — a database that finds things by meaning, not just matching words (Chroma; optional — degrades to empty context if unavailable)
- **NLP layer** — handles bulk text work like extracting entities and matching meanings across thousands of tests cheaply. The heavy models are **opt-in**: sentence-transformers embeddings (`EMBED_ALLOW_DOWNLOAD=1`) and spaCy NER (`SPACY_NER=1`); the **default path is deterministic** (hashing vectors, lexical-overlap similarity, keyword extraction) so the demo is fast and dependency-light
- **Test parsers** — translates every test framework's format into one language the agent can work with
- **Repo + Jira connectors** — how the agent actually reads your code and your tickets
- **Checkpointer** — saves everything when the agent pauses at a checkpoint, picks up exactly where it left off when a human responds. **In-memory by default** (`MemorySaver` — paused runs are lost on process restart, fine for the CLI/demo); set `CHECKPOINT_DB=<path.sqlite>` to swap in a **persistent SQLite saver** (`make_checkpointer()` in `src/graph.py`) so paused runs survive restarts when wiring up always-on automation
- **Sandbox executor** — runs generated tests in a sealed container so nothing can go wrong in your real system

**Why the LLM is reserved for judgement (deterministic NLP does the bulk):**
- One run can involve thousands of tests — running an LLM over each would be slow and costly
- Deterministic NLP (similarity, clustering, extraction) narrows the field first at near-zero cost and with no API dependency
- The LLM is called only where genuine reasoning is needed: scoring rationale, prioritisation trade-offs, writing gap-test code
- `REASONING_MODEL` / `FAST_MODEL` are kept as separate slots so a cheaper model can be slotted into `FAST_MODEL` later; today both default to `gemini-2.5-flash`

---

## 8. ADLC Journey

**Phase 0 — Discovery**
- The real problem wasn't missing tests — it was too many bad ones: slow, flaky, duplicated
- Agent won't start unless tests are version-controlled and have past run history to learn from

**Phase 1 — Scoping**
- Hard boundaries set before any code was written: can suggest removal not execute it, can write tests not commit them, cannot breach coverage floor
- Success metrics locked upfront: runtime down, redundancy down, flakiness rate down, coverage held, unapproved deletions = 0

**Phase 2 — Architecture**
- LLM use: Google Gemini (`gemini-2.5-flash`) reserved for Node 5 (scoring) and Node 7 (gap generation); classification, formatting and routing are deterministic NLP / code, not an LLM call
- Memory: short-term typed state object per run; long-term per-project store updated after every run — implemented as a per-project JSON file (`src/memory/store.py`: prior decisions, protected tests, known-flaky), not an embedding store

**Phase 3 — Build & Test**
- Wired to real repos and CI history, not synthetic data — every node decision logged to audit trail
- Thumbs up/down collected at each HITL to build per-project correction dataset

**Phase 4 — Deployment**
- 5% rollout to one team, all actions reversible, HITL mandatory regardless of run_mode
- Blast radius contained until correction rate is measurably low

**Phase 5 — Continuous Improvement**
- Checks back monthly because codebases change and the suite drifts with them
- Every human correction gets stored — agent learns from it. Only gets more independence when the correction rate actually drops, not just because time passed

---

## 9. Architecture — Node by Node

```mermaid
flowchart TD
    START([Trigger]) --> INTAKE[1 Intake & Normalise]
    INTAKE --> COVERAGE[2 Coverage & Gap Analysis]
    COVERAGE --> REDUNDANCY[3 Redundancy & Flakiness Detection]
    REDUNDANCY --> RETRIEVE[4 Context Retrieval RAG]
    RETRIEVE --> SCORE[5 Health Scoring]
    SCORE --> HIL1{{HITL 1: approve removals}}
    HIL1 --> PRIORITISE[6 Risk-based Prioritisation]
    PRIORITISE --> FLOOR{Coverage Floor Gate}
    FLOOR -->|below target| REVISE[Revise / drop removals]
    REVISE --> FLOOR
    FLOOR -->|target held| HIL2{{HITL 2: approve ranking}}
    HIL2 --> GAPGEN[7 Gap Test Generation]
    GAPGEN --> VALIDATE[8 Static Validation Sandbox]
    VALIDATE -->|invalid AND retries left| GAPGEN
    VALIDATE -->|retries exhausted| DROPGEN[Drop failing tests + flag]
    VALIDATE -->|valid| HIL3{{HITL 3: approve tests}}
    DROPGEN --> HIL3
    HIL3 --> ASSEMBLE[9 Assemble Optimised Plan]
    ASSEMBLE --> REPORT[10 Render Outputs]
    REPORT --> MEMORY[(Update long-term store)]
    MEMORY --> END([Plan delivered])
    ERR>Any tool failure: retry x3 then degrade] -.-> INTAKE
```

### Node 1 — Intake & Normalise
- Tests arrive from different frameworks all in different formats — translates everything into one common representation
- NLP breaks test names and docstrings into clean tokens and reduces words to root forms
- NER pulls out exactly what each test is touching — which endpoint, which module, which function
- *Implementation:* default is deterministic tokenise / lemmatise / keyword extraction; spaCy NER is opt-in (`SPACY_NER=1`). Unparseable tests are isolated and flagged, never silently dropped

### Node 2 — Coverage & Gap Analysis
- Checks which parts of your actual code each test exercises when it runs
- NLP converts both tests and requirements into embeddings, cosine similarity measures how close they are in meaning
- *Implementation:* default similarity is deterministic lexical overlap (threshold `CRITERIA_MATCH_THRESHOLD` / `GAP_THRESHOLD` = 0.45); real sentence-transformers embeddings are opt-in (`EMBED_ALLOW_DOWNLOAD=1`)

### Node 3 — Redundancy & Flakiness Detection
- Looks at past CI run history to find tests that randomly pass and fail = flaky
- Every flag comes with the evidence behind it, not just a label
- *Implementation:* duplicate clustering threshold `DUPLICATE_THRESHOLD` = 0.80. Flaky = `fails/runs >= FLAKY_FAIL_RATE` (10%), slow = `avg_seconds >= SLOW_TEST_SECONDS` (10s), read from CI history; missing history degrades to "needs more data"

### Node 4 — Context Retrieval (RAG)
- Before scoring anything, pulls relevant history from memory: past decisions, known patterns, project docs
- Stops the agent from flagging something a human already decided to keep in a previous run
- NLP embeds the query and fires it against the vector store

### Node 5 — Health Scoring
- Takes everything from nodes 2, 3, and 4 and produces a score for every test across multiple dimensions
- Each score has a reason and a recommended action attached — not just a number
- The LLM (Gemini) used here because explaining why a test scored low needs actual reasoning
- *Implementation:* uses Gemini with a strict-JSON prompt; on no key / offline / error it falls back to a deterministic rubric, and a dimension with no evidence is reported as "insufficient evidence" (score `null`), never guessed

### HITL 1 — Approve Removals
- Pipeline completely stops via LangGraph `interrupt()`
- Agent surfaces which tests it wants to remove and exactly why — full evidence attached
- Human can approve, reject, or change each recommendation
- Checkpointer saves entire state — pause can last hours or days, resumes exactly where it left off

### Node 6 — Risk-based Prioritisation
- Re-sorts surviving tests into three tiers: Smoke (every commit), Regression (merges), Full (nightly/release)
- Tests covering risk areas always pinned to smoke regardless of speed — safety overrides efficiency

### Coverage Floor Gate
- Recomputes projected coverage after approved removals are applied
- The revise loop is bounded by `MAX_REVISE_ITERS` (default 10) via a `revise_count` guard
- Cannot be skipped — no change set that breaches the coverage floor passes through
- Risk area tests are pinned and never eligible for removal at this gate

### HITL 2 — Approve Ranking
- Human reviews the proposed test tiering before it gets locked in
- State saved by checkpointer

### Node 7 — Gap Test Generation
- The LLM (Gemini) writes brand new test code for the top-ranked gaps found in Node 2
- Does not go anywhere near the real repo — output goes straight to sandbox
- If validation fails, this node is called again with the failure reason — up to 3 times, `gen_retry_count` enforces the ceiling
- *Implementation:* on no key / offline / error it emits a runnable convention-matching stub and records the degrade in `tool_errors`

### Node 8 — Static Validation Sandbox
- Generated tests run inside an isolated container completely cut off from real systems
- After 3 failed attempts tests are dropped and flagged as needing manual attention — run always continues

### HITL 3 — Approve Generated Tests
- Human reviews tests that passed sandbox validation
- Nothing reaches the real repo until explicitly approved here

### Node 9 — Assemble Optimised Plan
- Pulls all approved decisions together: what's kept, removed, re-tiered, and newly generated

### Node 10 — Render Outputs
- Produces all deliverables and writes everything learned from this run into long-term memory
- A rejected suggestion is never re-proposed

---

## 10. Typed State Schema

```python
from typing import TypedDict, Annotated, Literal
from operator import add

class TestOptimiserState(TypedDict, total=False):
    project_id: str
    suite_path: str
    raw_suite: list[dict]
    optimization_goal: Literal["speed", "coverage", "reliability", "cost"]
    coverage_target: float                # default 0.80
    risk_areas: list[str]
    additional_context: str
    run_mode: Literal["interactive", "automated"]
    normalised_suite: list[dict]
    coverage_map: dict
    projected_coverage: float
    coverage_gaps: list[dict]
    redundancy_flags: list[dict]
    flakiness_flags: list[dict]
    scorecard: dict
    approved_removals: list[str]
    approved_priority: dict
    approved_generated_tests: list[dict]
    gen_retry_count: int                  # bounds the validation loop
    revise_count: int                     # bounds the coverage-floor revise loop
    validation_passed: bool
    tool_errors: Annotated[list[dict], add]
    prioritised_plan: dict
    generated_tests: list[dict]
    final_outputs: dict
    audit_log: Annotated[list[dict], add]
```

- `tool_errors` and `audit_log` are append-only — they only ever grow, nothing is overwritten
- `gen_retry_count` bounds the Node 7 -> Node 8 loop, `revise_count` bounds the coverage-floor revise loop — both enforced in code, not just convention

---

## 11. Blocker Fixes

### 1 · Bounded Validation Loop
```python
MAX_GEN_RETRIES = 3
def route_after_validation(state) -> str:
    if state["validation_passed"]:
        return "approve_tests"
    if state["gen_retry_count"] >= MAX_GEN_RETRIES:
        return "drop_failing"
    return "gap_gen"
```
- Hard ceiling of 3 retries — loop cannot spin forever. Run always proceeds regardless.

### 2 · Enforced Coverage Floor Gate
```python
MAX_REVISE_ITERS = 10
def coverage_floor_gate(state) -> str:
    projected = recompute_coverage(state["normalised_suite"], state["approved_removals"])
    if projected >= state["coverage_target"]:
        return "approve_ranking"
    if state.get("revise_count", 0) >= MAX_REVISE_ITERS:
        return "approve_ranking"
    return "revise"
```
- Cannot pass a change set that breaches the floor — enforced in code not prose

### 3 · Tool-call Error Handling
```python
def call_tool(fn, *args, retries=3, backoff=2):
    for attempt in range(retries):
        try:
            return {"ok": True, "data": fn(*args)}
        except TransientError:
            time.sleep(backoff ** attempt)
        except FatalError as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "max_retries_exceeded"}
```

| Failed dependency | Degrade behaviour |
|-------------------|-------------------|
| Coverage report | Falls back to static call-graph estimate, marked low-confidence |
| CI history | Flakiness flags downgraded to "needs more data" |
| Vector store | Proceeds with empty context, flagged as "context thin" |
| Sandbox | Skips generation, delivers analysis + plan only |
| Repo (fatal) | Halts cleanly — only case where stopping is correct |

- Every degrade appended to `tool_errors` and shown in final report
- Transient errors: exponential backoff, `TOOL_RETRIES` retries (default 3)
- Fatal errors: no retry, immediate clean failure

---

## 12. Safety Controls

- Nothing destructive runs without explicit human approval at a HITL checkpoint
- Coverage floor enforced in code — hard block not a guideline
- Risk area tests permanently pinned, never eligible for removal
- Every action versioned and reversible — instant rollback available
- Full audit trail of every node, tool call, score, and approval throughout the run
- Generated tests only ever run in the sandbox, never against real systems
- Gradual rollout starting at 5% / one team
