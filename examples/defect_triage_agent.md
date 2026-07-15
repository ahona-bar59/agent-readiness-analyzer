# Defect Triage AI Agent

## Table of Contents
1. Project Overview
2. ADLC Phase 1 — Planning
3. ADLC Phase 2 — Design
4. ADLC Phase 3 — Development
5. ADLC Phase 4 — Testing
6. ADLC Phase 5 — Deployment
7. Risks & Mitigations
8. References

---

## 1. Project Overview

**DefectTriageBot** automates the process of reviewing, prioritizing, and routing software bug reports using an LLM-powered LangGraph agent.

### Problem Statement
Manual defect triage is slow (~45 min/bug), inconsistent, and error-prone. Duplicate bugs clog the backlog, severity assignments vary by individual, and wrong team routing wastes developer time.

### Why Automation
| Problem | Impact |
|---------|--------|
| Manual severity assignment | ~45 min per bug |
| Duplicate bugs in backlog | ~18% of backlog |
| Wrong team routing | ~30% re-assignments |
| Delayed critical bug alerts | 4-8 hours response time |

### Expected Outcomes
| Metric | Target |
|--------|--------|
| Triage time | < 2 min/bug |
| Duplicate detection | < 3% slip-through |
| Critical bug alert | < 15 minutes |
| QA lead hours saved | ~10 hrs/sprint |

---

## 2. ADLC Phase 1 — Planning

### Goals
1. Ingest defects from Jira, GitHub Issues, or REST API
2. Analyze root cause and affected component using LLM
3. Detect duplicates via vector similarity
4. Classify severity: Critical / High / Medium / Low
5. Assign to the correct team and developer
6. Notify via Slack and email; update Jira ticket

### Scope
**In Scope** — Defect ingestion, analysis, duplicate detection, severity classification, assignment, notification
**Out of Scope** — Automated bug fixing, test case generation, UI dashboard (v1)

### Tools & Integrations
| Tool | Purpose |
|------|---------|
| Jira / GitHub Issues | Ticket management |
| Slack | Real-time notifications |
| ChromaDB / Pinecone | Vector store for duplicate detection |
| LangSmith | Tracing and evaluation |
| Anthropic Claude Sonnet 4.6 | Primary LLM |
| OpenAI text-embedding-3-small | Embeddings |

### LLM Rationale
Claude Sonnet 4.6 is selected for its 200k context window (handles large stack traces), reliable structured JSON output, and cost-effective throughput.

---

## 3. ADLC Phase 2 — Design

### LangGraph Flow
```mermaid
flowchart TD
    START([START]) --> intake["intake_defect: Parse & validate input, Extract image attachments"]
    intake --> check_dup["check_duplicate: Vector similarity search, Regression detection"]
    check_dup --> dup_gate{Match result?}
    dup_gate -- "DUPLICATE (open match >= 0.88)" --> flag_dup["flag_duplicate: Link to parent ticket"]
    dup_gate -- "REGRESSION (closed match >= 0.88)" --> analyze["analyze_defect: LLM root cause + category, Multimodal text + images"]
    dup_gate -- "NEW BUG (no match)" --> analyze
    analyze --> prioritize["prioritize: LLM severity + priority"]
    prioritize --> sev_gate{Severity?}
    sev_gate -- CRITICAL --> escalate["escalate: Page on-call"]
    sev_gate -- HIGH/MED/LOW --> assign["assign_defect: Route to team + dev"]
    escalate --> assign
    assign --> notify["notify: Jira + Slack + Email"]
    flag_dup --> END([END])
    notify --> END
```

### State Schema
```python
class TriageState(TypedDict):
    defect_id: str
    title: str
    description: str
    stack_trace: str
    environment: str
    reporter: str
    image_attachments: Annotated[list[dict], operator.add]
    category: str
    component: str
    root_cause: str
    is_duplicate: bool
    duplicate_of: str
    is_regression: bool
    regression_of: str
    similar_defects: Annotated[list[dict], operator.add]
    severity: str       # CRITICAL | HIGH | MEDIUM | LOW
    priority: int       # 1 (highest) to 4 (lowest)
    assigned_team: str
    assigned_to: str
    triage_notes: Annotated[list[str], operator.add]
    status: str
```

### Node Summary
| Node | Responsibility | LLM? |
|------|---------------|------|
| `intake_defect` | Parse and normalize input; extract image attachments | No |
| `check_duplicate` | Vector similarity vs. backlog; detect regression if match is RESOLVED/CLOSED | No |
| `analyze_defect` | Root cause, category, component; multimodal (text + base64 images) | Yes |
| `prioritize` | Severity and priority assignment | Yes |
| `assign_defect` | Component -> team -> developer routing | No |
| `escalate` | Page on-call for CRITICAL bugs | No |
| `flag_duplicate` | Link to parent, close as duplicate | No |
| `notify` | Jira update + Slack + Email | No |

---

## 4. ADLC Phase 3 — Development

### Tech Stack
| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Agent Framework | LangGraph 1.0+ |
| LLM | Anthropic Claude Sonnet 4.6 |
| Embeddings | OpenAI text-embedding-3-small |
| API Server | FastAPI |
| Vector Store | ChromaDB (local) / Pinecone (cloud) |
| Tracing | LangSmith |

### Project Structure
```
defect-triage-agent/
  app/
    agent/
      graph.py          # StateGraph definition
      state.py          # TriageState schema
      nodes/
        intake.py, analyze.py, duplicate.py, prioritize.py,
        assign.py, escalate.py, flag_dup.py, notify.py
    tools/
      jira_tool.py, slack_tool.py, vector_store.py
    api/
      routes.py         # POST /triage + serves the React UI at /
  frontend/             # React 18 + Vite UI (post-v1 addition)
  tests/
  .env.example
  Dockerfile
  docker-compose.yml
```

> **Post-v1 extensions (implemented beyond this original spec):** live Jira integration
> (fetch a defect by ID -> auto-fill; write the triage result back to the source issue,
> else create a Bug); SSE streaming on `POST /triage` with a live log feed; error modal /
> warning toasts; and a **human-in-the-loop** pause where `assign_defect` uses LangGraph
> `interrupt()` to let a user pick the assignee, resumed via `POST /triage/resume`.

### Core Graph Definition
```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy
from typing import Literal

def route_after_check(state) -> Literal["flag_duplicate", "analyze_defect"]:
    return "flag_duplicate" if state["is_duplicate"] else "analyze_defect"

def route_severity(state) -> Literal["escalate", "assign_defect"]:
    return "escalate" if state["severity"] == "CRITICAL" else "assign_defect"

def build_graph():
    builder = StateGraph(TriageState)
    builder.add_node("intake_defect", intake_defect)
    builder.add_node("check_duplicate", check_duplicate)
    builder.add_node("analyze_defect", analyze_defect, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("prioritize", prioritize, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("assign_defect", assign_defect)
    builder.add_node("escalate", escalate)
    builder.add_node("flag_duplicate", flag_duplicate)
    builder.add_node("notify", notify)
    builder.add_edge(START, "intake_defect")
    builder.add_edge("intake_defect", "check_duplicate")
    builder.add_conditional_edges("check_duplicate", route_after_check, ["flag_duplicate", "analyze_defect"])
    builder.add_edge("analyze_defect", "prioritize")
    builder.add_conditional_edges("prioritize", route_severity, ["escalate", "assign_defect"])
    builder.add_edge("escalate", "assign_defect")
    builder.add_edge("assign_defect", "notify")
    builder.add_edge("notify", END)
    builder.add_edge("flag_duplicate", END)
    return builder.compile()
```

### Sample Node — `check_duplicate`
```python
SIMILARITY_THRESHOLD = 0.88
RESOLVED_STATUSES = {"RESOLVED", "CLOSED", "DONE"}

def check_duplicate(state: TriageState) -> dict:
    query = f"{state['title']} {state['description']}"
    results = get_vector_store().similarity_search_with_score(query, k=5)
    for doc, score in results:
        if score < SIMILARITY_THRESHOLD:
            continue
        matched_status = doc.metadata.get("status", "").upper()
        matched_id = doc.metadata.get("defect_id", "")
        if matched_status in RESOLVED_STATUSES:
            return {"is_duplicate": False, "is_regression": True, "regression_of": matched_id,
                    "status": "in_triage", "triage_notes": [f"REGRESSION of resolved defect {matched_id}"]}
        else:
            return {"is_duplicate": True, "duplicate_of": matched_id, "is_regression": False,
                    "status": "duplicate", "triage_notes": [f"DUPLICATE of open defect {matched_id}"]}
    return {"is_duplicate": False, "is_regression": False, "status": "in_triage",
            "triage_notes": ["No match found - new defect"]}
```

---

## 5. ADLC Phase 4 — Testing

### Strategy
| Level | Tool | Focus |
|-------|------|-------|
| Unit | pytest + mock | Each node in isolation |
| Integration | pytest (live) | Full graph end-to-end |
| LLM Eval | LangSmith | Severity accuracy |

### Sample Test Scenarios
| Scenario | Expected Severity | Expected Route |
|----------|------------------|----------------|
| Payment service down (prod, all users) | CRITICAL | Check Dup -> Analyze -> Escalate -> Assign -> Notify |
| Button misaligned in staging | LOW | Check Dup -> Analyze -> Assign -> Notify |
| Duplicate of open DEF-101 | N/A | Flag Duplicate -> END (LLM skipped) |
| Same symptoms as CLOSED DEF-050 | HIGH | Check Dup -> Analyze (regression) -> Assign -> Notify |

### Evaluation Metrics
| Metric | Target |
|--------|--------|
| Severity accuracy | >= 90% |
| Duplicate precision | >= 95% |
| Assignment accuracy | >= 85% |
| Avg. triage latency | < 10 seconds |

---

## 6. ADLC Phase 5 — Deployment

### Deployment Options
| Option | How |
|--------|-----|
| Local | `uvicorn app.api.routes:app --reload` |
| Docker | `docker build + docker run --env-file .env` |
| Docker Compose | `docker compose up -d` (agent + ChromaDB) |

### Key Environment Variables
```env
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_API_TOKEN=...
SLACK_WEBHOOK_URL=...
LANGSMITH_API_KEY=...
LANGCHAIN_TRACING_V2=true
```

### Monitoring
| Tool | Purpose |
|------|---------|
| LangSmith | LLM traces, latency, token usage |
| structlog | Structured JSON logs per node |
| Sentry | Unhandled exceptions |

---

## 7. Risks & Mitigations
| Risk | Mitigation |
|------|-----------|
| LLM incorrect severity | Rule-based override for known CRITICAL keywords |
| Duplicate false positive | Human review for similarity score 0.80-0.88 |
| Regression misidentified as new bug | Track defect status in vector store metadata; refresh on ticket close/resolve |
| Large image attachments slowing triage | Cap image size (max 5 MB per image, max 3 images); strip unsupported formats |
| Jira API rate limiting | Exponential backoff + request queue |
| LLM provider outage | Fallback to rule-based classifier |
| PII in bug reports or screenshots | PII scrubber on text; avoid logging raw image data |

---

## 8. References
- LangGraph Documentation: https://langchain-ai.github.io/langgraph/
- LangGraph StateGraph API
- LangSmith Tracing
- Jira REST API v3
- GitHub Issues API
- ChromaDB Documentation
