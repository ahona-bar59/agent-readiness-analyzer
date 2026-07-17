"""The ARA rubric: 8 dimensions, hard gates, and the failure-cluster taxonomy.

This module is the single source of truth for *what* ARA scores and *why*. It is
data-driven so both the heuristic scorer and the LLM prompt build from the same
definitions. Each dimension cites the AWS / Google / Microsoft framework(s) that
back it (see README section 7).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dimension:
    key: str
    name: str
    what_it_checks: str
    framework_refs: list[str]
    # `signals` are evidence phrases (lower-cased) that indicate the dimension is
    # addressed. The heuristic scorer counts distinct matches; the LLM scorer uses
    # them as guidance for what to look for.
    signals: list[str]
    # `expected` phrases that, when absent, are reported as gaps.
    expected: list[str] = field(default_factory=list)


DIMENSIONS: list[Dimension] = [
    Dimension(
        key="security",
        name="Security & Safety",
        what_it_checks=(
            "PII masking, injection/jailbreak defense, input limits, guarded writes, "
            "output validation, least-privilege access"
        ),
        framework_refs=["AWS AGENTSEC01/04/05/08", "Google Safety metrics", "MS jailbreak/content-safety"],
        signals=[
            "pii", "prompt injection", "injection", "jailbreak", "guardrail",
            "mask", "content safety", "input validation", "least privilege",
            "sanitize", "redact", "allowlist", "confidence-based classifier",
        ],
        expected=["prompt injection", "pii", "least privilege"],
    ),
    Dimension(
        key="reliability",
        name="Reliability & Robustness",
        what_it_checks=(
            "Termination guarantee, retries, escalation, fallbacks, graceful "
            "degradation under stochastic output"
        ),
        framework_refs=["AWS AGENTREL", "MS Reliability pillar (failure simulation)"],
        signals=[
            "retry", "retry_count", "termination", "fallback", "escalate",
            "best-effort", "max retries", "recover", "timeout", "circuit breaker",
            "idempoten", "always reaches the end", "never loops forever",
            "graceful degrad", "degrade", "never crash", "resume", "checkpointer",
            "sequential", "bounded",
        ],
        expected=["fallback", "graceful degrad"],
    ),
    Dimension(
        key="autonomy",
        name="Autonomy & Human Oversight",
        what_it_checks=(
            "Autonomy level (L1-L4), HITL gates, bounded autonomy, oversight tiered "
            "to risk/reversibility"
        ),
        framework_refs=["AWS AGENTSEC02 / Responsible-AI", "MS HITL governance"],
        signals=[
            "hitl", "human-in-the-loop", "human in the loop", "human approval",
            "approval", "interrupt", "blocking gate", "supervised", "human approves",
            "review gate", "l1", "l2", "l3", "l4", "bounded autonomy",
        ],
        expected=["human approval", "gate"],
    ),
    Dimension(
        key="task_effectiveness",
        name="Task Effectiveness & Goal Alignment",
        what_it_checks=(
            "Intent resolution, task adherence, groundedness, measurable task success"
        ),
        framework_refs=[
            "AWS AGENTOPS06 (goal alignment)",
            "Google Task Success / Intent Resolution",
            "MS Intent Resolution / Task Adherence / Groundedness",
        ],
        signals=[
            "acceptance criteria", "success metric", "completeness", "correctness",
            "intent", "task adherence", "grounded", "goal", "self-review",
            "quality gate", "task success", "measurable", "coverage", "validated",
            "golden", "constraint", "invariant",
        ],
        expected=["success metric", "measurable"],
    ),
    Dimension(
        key="tools",
        name="Tool & Integration Correctness",
        what_it_checks=(
            "Tool scoping/allowlisting, correct selection & parameters, guarded write "
            "tools, MCP standardization"
        ),
        framework_refs=["AWS AGENTSEC03 (tool governance)", "Google Tool-Use Quality", "MS Tool-Call Accuracy"],
        signals=[
            "tool", "mcp", "allowlist", "guarded write", "tool governance",
            "scoped", "function call", "megatool", "tool grouping", "json-rpc",
            "connector", "vector store", "database", "sandbox", "endpoint", "api",
            "gated", "read-before-write", "read-only", "constraint-validated",
        ],
        expected=["guarded write", "scoped"],
    ),
    Dimension(
        key="performance",
        name="Performance & Cost Efficiency",
        what_it_checks=(
            "Latency vs. manual baseline, batching, dedup, reasoning-loop cost control, "
            "model right-sizing"
        ),
        framework_refs=["AWS AGENTPERF / AGENTCOST", "MS Performance pillar"],
        signals=[
            "latency", "token", "cost", "batch", "dedup", "duplicate",
            "temperature", "throughput", "cache", "right-size", "run duration",
            "minutes", "self-correction", "offline", "deterministic", "lightweight",
            "negligible", "near-zero", "cheap",
        ],
        expected=["cost"],
    ),
    Dimension(
        key="observability",
        name="Observability & Evaluation",
        what_it_checks=(
            "Tracing, LLM-as-judge eval, drift/decay monitoring, feedback capture, rollback"
        ),
        framework_refs=["AWS AGENTOPS05/06", "Google failure-cluster eval", "MS observability/drift"],
        signals=[
            "trace", "tracing", "langsmith", "observability", "monitor", "drift",
            "telemetry", "logging", "metrics", "dashboard", "feedback", "jsonl",
            "rollback", "feature flag", "websocket",
        ],
        expected=["tracing", "drift", "rollback"],
    ),
    Dimension(
        key="architecture",
        name="Architecture & Scope Clarity",
        what_it_checks=(
            "Node/graph clarity, state mgmt, checkpointing, clear does/does-NOT, "
            "measurable success metrics"
        ),
        framework_refs=["AWS AGENTOPS01/03", "MS Operational Excellence"],
        signals=[
            "node", "state", "checkpoint", "stategraph", "langgraph", "schema",
            "pydantic", "scope", "does not", "workflow", "graph", "deterministic routing",
        ],
        expected=["node", "state", "scope"],
    ),
]

DIMENSIONS_BY_KEY = {d.key: d for d in DIMENSIONS}


# Friendly display names for the lower-cased rubric `expected` phrases, so reports
# read as human prose ("least-privilege access") rather than raw match tokens
# ("least privilege") or truncated stems ("graceful degrad").
EXPECTED_DISPLAY: dict[str, str] = {
    "prompt injection": "prompt-injection defense",
    "pii": "PII handling",
    "least privilege": "least-privilege access",
    "fallback": "fallback paths",
    "graceful degrad": "graceful degradation",
    "human approval": "human approval",
    "gate": "human approval gates",
    "success metric": "success metrics",
    "measurable": "measurable success criteria",
    "guarded write": "guarded writes",
    "scoped": "scoped tool access",
    "cost": "cost controls",
    "tracing": "tracing",
    "drift": "drift monitoring",
    "rollback": "rollback support",
    "node": "node / graph structure",
    "state": "state management",
    "scope": "clear in / out-of-scope",
}


def display_term(term: str) -> str:
    """Human-friendly label for a rubric expected-phrase (falls back to the raw
    term, with common acronyms upper-cased)."""
    if term in EXPECTED_DISPLAY:
        return EXPECTED_DISPLAY[term]
    return "PII" if term == "pii" else term


# --------------------------------------------------------------------------- #
# Hard gates — non-negotiable safety conditions. A FAIL forces NOT_DEPLOYABLE
# when strict_gates is on, regardless of total score. Each gate is evaluated by
# a detector in verdict.py; this table drives labelling and reporting.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateDef:
    key: str
    description: str
    backed_by: str
    severity: str


HARD_GATES: list[GateDef] = [
    GateDef(
        "guarded_writes",
        "Agent can write to a real system without an approval/guard step.",
        "AWS AGENTSEC08, bounded autonomy",
        "critical",
    ),
    GateDef(
        "termination_guarantee",
        "No bound on loops/retries - the run could loop forever.",
        "AWS AGENTREL, bounded execution",
        "critical",
    ),
    GateDef(
        "injection_defense",
        "No prompt-injection/jailbreak protection on untrusted input.",
        "AWS AGENTSEC04/08, Google Safety, MS jailbreak testing",
        "high",  # caps verdict at CONDITIONAL rather than hard-blocking
    ),
    GateDef(
        "no_self_deploy",
        "Agent can grant itself autonomy / bypass its own gates.",
        "AWS AGENTSEC07 (detect rogue agents)",
        "critical",
    ),
    GateDef(
        "safety_screening",
        "No PII/harmful-content handling anywhere in the pipeline.",
        "Google Safety metric, MS content-safety testing",
        "high",
    ),
]


# --------------------------------------------------------------------------- #
# Failure-cluster taxonomy (Google Automatic-Loss-Analysis style). Each entry
# maps a set of dimension gaps to a named systemic cluster. clustering.py uses
# `trigger_dimensions` + gap keywords to assign findings to clusters.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ClusterDef:
    name: str
    severity: str
    framework_source: str
    trigger_dimensions: list[str]
    description: str = ""


CLUSTER_TAXONOMY: list[ClusterDef] = [
    ClusterDef(
        "Unsafe autonomy", "critical", "AWS AGENTSEC02/08; Google autonomy gaps",
        ["autonomy", "security"],
        "The agent acts with meaningful autonomy, but the safety controls around those "
        "actions aren't evidenced — actions could take effect without adequate guarding.",
    ),
    ClusterDef(
        "Privilege escalation", "critical", "AWS AGENTSEC07", ["autonomy"],
        "Signals suggest the agent could expand its own permissions or autonomy — this "
        "must never happen without explicit human control.",
    ),
    ClusterDef(
        "Weak input defense", "high", "AWS AGENTSEC04; Google Safety", ["security"],
        "Untrusted input isn't clearly defended (e.g. prompt injection), leaving the "
        "agent open to manipulation.",
    ),
    ClusterDef(
        "Untrusted output handling", "high", "Google Failure Cluster: Data Leakage",
        ["security", "tools"],
        "Tool or model outputs may carry unsanitised or sensitive data downstream, "
        "creating a data-leakage risk.",
    ),
    ClusterDef(
        "Tool-use errors", "medium", "Google Tool-Use Quality; AWS AGENTSEC03", ["tools"],
        "Tool selection, scoping, or parameters aren't clearly governed, so the agent "
        "may call tools incorrectly or unsafely.",
    ),
    ClusterDef(
        "Goal misalignment", "medium", "Google Task Success; MS Intent Resolution",
        ["task_effectiveness"],
        "Success criteria and intent-grounding are thin, so the agent may drift from "
        "what the user actually asked for.",
    ),
    ClusterDef(
        "Blind operation", "high", "AWS AGENTOPS05/06; MS decay monitoring", ["observability"],
        "There's little tracing, monitoring, or drift detection — problems in production "
        "would be hard to see or catch.",
    ),
    ClusterDef(
        "Fragile reliability", "high", "AWS AGENTREL", ["reliability"],
        "Failure handling (termination bounds, retries, fallbacks) isn't well evidenced, "
        "so the agent may behave unpredictably under stress.",
    ),
]
