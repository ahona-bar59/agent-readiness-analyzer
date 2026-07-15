"""Input Requirements Checklist — the client-facing "what your README must document".

When a client submits a vague / undetailed README, ARA must not just say "low
confidence" — it must tell the client *exactly* which dimensions and parameters
have to be positively present for a proper analysis, scoring, and deployability
check to be possible. This module produces that checklist: each requirement is
marked PRESENT / PARTIAL / MISSING against the actual artifact, split into
MANDATORY (blocking a deployability decision) and RECOMMENDED (needed for a full
score). The report layer turns the MISSING/PARTIAL items into a document you can
send straight back to the client.

The prose here is deliberately human-readable and separate from `rubric.py` (whose
`signals`/`expected` are lower-cased matching phrases, not client-facing text).
"""
from __future__ import annotations

from .rubric import DIMENSIONS
from .schema import DimensionScore, HardGate, RequirementItem

# The concrete parameters a README must document, per dimension (keyed by rubric
# dimension key). These are what a reviewer needs to see to score the dimension.
DIMENSION_REQUIREMENTS: dict[str, list[str]] = {
    "security": [
        "Prompt-injection / jailbreak defense on untrusted input",
        "PII / sensitive-data handling (masking, redaction)",
        "Input validation and size limits",
        "Least-privilege access to tools and data",
        "Output validation before any write",
    ],
    "reliability": [
        "Termination guarantee (retry / iteration limits, timeouts)",
        "Fallback and escalation paths when a step fails",
        "Graceful degradation under bad or stochastic output",
        "Recovery / checkpointing behaviour",
    ],
    "autonomy": [
        "Declared autonomy level (L1-L4)",
        "Human-in-the-loop / approval gates and where they sit",
        "Which actions require human sign-off before taking effect",
    ],
    "task_effectiveness": [
        "Measurable success / acceptance criteria",
        "How the agent stays grounded to the requested intent",
        "Task-adherence or self-review checks",
    ],
    "tools": [
        "Which external tools / systems the agent calls",
        "Tool scoping / allowlisting",
        "Guarded write tools (read-before-write, gating)",
        "Integration standard (e.g. MCP), if any",
    ],
    "performance": [
        "Latency versus the manual baseline",
        "Token / cost controls (batching, caching, dedup)",
        "Model right-sizing / expected run duration",
    ],
    "observability": [
        "Tracing / logging in production",
        "Drift or decay monitoring",
        "Feedback capture and rollback mechanism",
    ],
    "architecture": [
        "Node / graph / state structure",
        "Explicit in-scope and out-of-scope (does / does NOT)",
        "State management / checkpointing",
    ],
}

# Dimensions that MUST be documented before a deployability decision can be made
# at all — the safety triad. The rest are needed for a full score but are not
# individually blocking. (Mirrors the prime-dimension / safety-triad philosophy.)
MANDATORY_DIMENSIONS = {"security", "reliability", "autonomy"}

# The non-negotiable safety controls behind each hard gate, phrased as something
# the README must positively state. Absence of these blocks a clean assessment.
GATE_REQUIREMENTS: dict[str, str] = {
    "guarded_writes": "Confirm that any write to a real system passes an approval / guard step.",
    "termination_guarantee": "State an explicit bound on loops / retries (max iterations, timeout).",
    "injection_defense": "Document prompt-injection / jailbreak protection on untrusted input.",
    "no_self_deploy": "Confirm the agent cannot grant itself autonomy or bypass its own gates.",
    "safety_screening": "Document PII / harmful-content handling somewhere in the pipeline.",
}


def _dimension_status(score: float) -> str:
    if score >= 1.5:
        return "PRESENT"
    if score > 0.0:
        return "PARTIAL"
    return "MISSING"


def build_requirements_checklist(
    dimensions: list[DimensionScore], hard_gates: list[HardGate]
) -> list[RequirementItem]:
    """Build the full requirements checklist: gates first (deployment
    prerequisites), then the 8 dimensions, each marked against the artifact."""
    name_to_key = {d.name: d.key for d in DIMENSIONS}
    items: list[RequirementItem] = []

    # 1. Hard-gate safety controls — the deployment prerequisites.
    for g in hard_gates:
        items.append(
            RequirementItem(
                area=g.gate.replace("_", " ").title(),
                category="gate",
                status="PRESENT" if g.status == "PASS" else "MISSING",
                mandatory=True,
                required_parameters=[GATE_REQUIREMENTS.get(g.gate, g.evidence)],
                note=f"Backed by hard gate '{g.gate}' ({g.severity}).",
            )
        )

    # 2. The 8 rubric dimensions.
    for d in dimensions:
        key = name_to_key.get(d.name, "")
        items.append(
            RequirementItem(
                area=d.name,
                category="dimension",
                status=_dimension_status(d.score),
                mandatory=key in MANDATORY_DIMENSIONS,
                required_parameters=DIMENSION_REQUIREMENTS.get(key, []),
                note=f"Scored {d.score}/2.",
            )
        )
    return items


def outstanding_requirements(items: list[RequirementItem]) -> list[RequirementItem]:
    """The items a client still needs to address (not fully PRESENT)."""
    return [i for i in items if i.status != "PRESENT"]
