# User Story Refinement Agent — Design Document
### For: Product Management Team | Framework: LangGraph | Structured by ADLC

> **Status:** Design draft for POC review. No implementation yet. Build proceeds only after sign-off.

---

## 1. Overview
The **User Story Refinement Agent** takes thin, vague, or underspecified user stories and enriches them into well-formed, INVEST-aligned stories with explicit context and testable acceptance criteria. Built as a **LangGraph** stateful graph, it loops between refinement and clarification until the story is "ready," then emits a structured output for the PM team.

### Reference Example (the target behavior)
**Input**
```
As a user, I want to log in so I can access my account.
```
**Output**
```
As a registered user, I want to log in with my email and password
so that I can securely access my personalised dashboard.

AC-1: Valid credentials redirect to the dashboard with an 8-hour session.
AC-2: Wrong password shows a generic error, with no hint as to whether the email exists.
```
The agent's job: sharpen the **persona**, **action**, and **benefit**, then generate **specific, testable acceptance criteria** without inventing scope the team didn't imply.

---

## 2. ADLC Phases

### Phase 1 — Requirements & Scoping
**Goal:** Define what the agent must and must not do.
- **Functional:** Parse the raw story, identify weak/missing parts, enrich persona, action, benefit, generate acceptance criteria, flag genuine ambiguities.
- **Non-functional:** Deterministic schema output, max 3 clarifying questions per cycle, latency < 3s/turn.
- **In scope:** Refining user stories and producing acceptance criteria.
- **Out of scope:** Writing code, estimating effort, prioritizing the backlog, implementing the feature.
- **Exit criteria:** Approved I/O contract + quality definition of "good story."

### Phase 2 — Design (Architecture & State)
**Goal:** Define the LangGraph topology, state schema, node responsibilities (Sections 4-5).
- **Exit criteria:** Reviewed graph diagram + state schema (this document).

### Phase 3 — Data & Prompt Engineering
**Goal:** Define prompts, examples, and the "weakness taxonomy."
- Author node prompts.
- Build the weakness taxonomy: vague persona, vague action, missing benefit, no acceptance criteria, untestable criteria, hidden assumptions, edge cases ignored.
- Curate golden before/after story pairs (like the login example).
- **Exit criteria:** Versioned prompt set + golden dataset.

### Phase 4 — Implementation
**Goal:** Build the LangGraph graph and node functions.
- Implement state, nodes, conditional edges, structured output parser.
- **Exit criteria:** Runnable graph passing smoke tests.

### Phase 5 — Evaluation & Testing
**Goal:** Validate refinement quality.
- Eval metrics: persona/action/benefit completeness, AC testability, INVEST adherence, no scope invention.
- Adversarial cases: empty story, already-perfect story, contradictory story, non-story input.
- **Exit criteria:** Metrics meet agreed thresholds.

### Phase 6 — Deployment
**Goal:** Ship behind a stable interface.
- Package graph, expose invoke API, config (`mode`, model, limits).
- **Exit criteria:** Versioned, deployable artifact with rollback path.

### Phase 7 — Monitoring & Iteration
**Goal:** Observe and improve.
- Log refinement outcomes, clarification rates, PM acceptance/edit rates.
- Feed rejected refinements back into prompts/examples (return to Phase 3).
- **Exit criteria:** Dashboards + feedback loop established.

---

## 3. Input / Output Contract

### Inputs
| Field | Type | Description |
|-------|------|-------------|
| `raw_story` | string | The original user story. |
| `context` | object (optional) | Product area, known personas, related stories, constraints. |
| `mode` | enum | `auto_resolve` (enrich from sensible defaults, ask only when blocked) or `strict` (ask before assuming). |

### Output (structured)
```json
{
  "refined_story": "As a <persona>, I want <action> so that <benefit>.",
  "persona": "Who the story is for.",
  "action": "What they want to do.",
  "benefit": "Why it matters to them.",
  "acceptance_criteria": ["AC-1: ...", "AC-2: ..."],
  "assumptions": ["Assumptions made while enriching."],
  "open_questions": ["Clarifying questions; empty if none."],
  "invest_check": {
    "independent": true, "negotiable": true, "valuable": true,
    "estimable": true, "small": true, "testable": true
  },
  "ready": true
}
```
`ready` is `true` only when the story is well-formed and testable; otherwise `open_questions` must be non-empty.

---

## 4. LangGraph State Schema

```python
from typing import TypedDict, List, Optional, Literal

class StoryState(TypedDict):
    raw_story: str
    context: Optional[dict]
    mode: Literal["auto_resolve", "strict"]
    persona: str
    action: str
    benefit: str
    acceptance_criteria: List[str]
    weaknesses: List[dict]       # {type, description, resolvable}
    assumptions: List[str]
    open_questions: List[str]
    invest_check: dict
    refined_story: str
    ready: bool
    cycle_count: int             # guards against infinite loops
```

---

## 5. LangGraph Topology

### Nodes
| Node | Responsibility |
|------|----------------|
| `parse_story` | Split raw story into persona / action / benefit; detect what's missing. |
| `detect_weaknesses` | Classify gaps against the weakness taxonomy. |
| `enrich_or_flag` | Sharpen persona/action/benefit from context (record assumptions) or queue questions. |
| `generate_acceptance_criteria` | Produce specific, testable AC including key edge cases. |
| `await_clarification` | Human-in-the-loop pause to collect PM answers. |
| `invest_validate` | Score the story against INVEST; route back if it fails. |
| `assemble_output` | Build structured output, set `ready`. |

### Conditional Routing
- After `enrich_or_flag`: unresolved critical gaps **and** `cycle_count < max` -> `await_clarification`; else -> `generate_acceptance_criteria`.
- After `await_clarification` -> loop back to `detect_weaknesses` with new info.
- After `invest_validate`: pass -> `assemble_output`; fail -> `detect_weaknesses` (bounded by `cycle_count`).

### Flow Diagram
```
        START
          |
      parse_story
          |
   detect_weaknesses  <-------------------+
          |                               |
     enrich_or_flag                       |
          |                               |
   [ gaps remaining? ] --yes--> await_clarification
          |                          (PM input)
          no
          |
  generate_acceptance_criteria
          |
    invest_validate --fail--> (back to detect_weaknesses)
          |
         pass
          |
    assemble_output
          |
         END
```

---

## 6. Guardrails
- **Enrich, don't invent:** never add scope, features, or constraints the team didn't imply; record every enrichment in `assumptions`.
- The agent does not estimate, prioritize, or implement.
- `cycle_count` cap prevents infinite refinement loops.
- Acceptance criteria must be **testable** (observable pass/fail), not vague intentions.
- A non-story or out-of-scope input -> `ready: false` with a flag in `open_questions`.
- Original intent always takes priority over rewriting style.

---

## 7. Open Questions for POC Review
1. Should `await_clarification` use LangGraph's `interrupt` (human-in-the-loop), or should the POC run single-pass auto-resolve?
2. What's the `max` cycle count before forcing output?
3. Which LLM/model for the POC?
4. Should the output feed a destination (e.g. Jira) in v1, or stay as structured text for now?
5. Do you have an existing persona library / "definition of ready" the agent should align to?
6. Should `invest_validate` block output on failure, or just warn?

---

> **Next step:** Review this design. On approval, proceed to **Phase 3 (prompts + golden story dataset)** and **Phase 4 (implementation)**.
