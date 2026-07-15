"""Input Completeness Assessor.

Answers the question a client's *vague* README forces on ARA: "is this a weak
agent, or just a weakly-documented one?" A sparse artifact means the evidence
needed to certify the agent is ABSENT, not that a problem is PRESENT — and those
must not be scored the same way.

This node measures how much the artifact actually gives the scorers to work with
(across four auditable factors), maps that to a completeness tier + an assessment
confidence, and — crucially — turns every un-evidenced dimension into a targeted
clarifying question the client can answer to unlock a full, high-confidence
assessment. The scoring math is unchanged; this is an interpretation layer that
keeps ARA honest about how far the input can be trusted.
"""
from __future__ import annotations

import re

from .rubric import DIMENSIONS
from .schema import DimensionScore, InputCompleteness

_WORD_RE = re.compile(r"\b\w+\b")
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s")

# The three deployment-critical dimensions. If the artifact says nothing about
# any of them, confidence is anchored low no matter how long the prose is — you
# cannot certify safety/reliability/oversight you were never told about.
_SAFETY_TRIAD = ("Security & Safety", "Reliability & Robustness", "Autonomy & Human Oversight")

# Full-marks anchors for the length/structure factors. A concise-but-complete
# README should top out here, so brevity alone never reads as "sparse".
_WORDS_FULL = 350.0
_HEADINGS_FULL = 6.0

# One targeted question per dimension, surfaced only when that dimension has no
# evidence at all. Keyed by dimension name so it tracks the rubric.
_QUESTIONS: dict[str, str] = {
    "Security & Safety": (
        "Security & Safety: how is untrusted input defended (prompt-injection / "
        "jailbreak handling), and how are PII / sensitive data treated "
        "(masking, redaction, least-privilege access)?"
    ),
    "Reliability & Robustness": (
        "Reliability & Robustness: what guarantees the agent terminates "
        "(retry / iteration limits, timeouts), and what are its fallback and "
        "escalation paths when a step fails?"
    ),
    "Autonomy & Human Oversight": (
        "Autonomy & Human Oversight: what is the agent's autonomy level, and "
        "where does a human approve or review its actions before they take effect?"
    ),
    "Task Effectiveness & Goal Alignment": (
        "Task Effectiveness: how is task success measured (acceptance criteria / "
        "success metrics), and how does the agent stay grounded to the request?"
    ),
    "Tool & Integration Correctness": (
        "Tools & Integrations: which external tools or systems does the agent "
        "call, are they scoped / allowlisted, and are write actions guarded?"
    ),
    "Performance & Cost Efficiency": (
        "Performance & Cost: what are the agent's latency and cost characteristics "
        "versus the manual baseline (batching, caching, model right-sizing)?"
    ),
    "Observability & Evaluation": (
        "Observability: how is the agent traced and monitored in production, and "
        "is there drift monitoring, feedback capture, or rollback?"
    ),
    "Architecture & Scope Clarity": (
        "Architecture & Scope: what is the agent's structure (nodes / state / "
        "workflow), and what is explicitly in and out of scope?"
    ),
}


def _tier_and_confidence(pct: int, triad_covered: int) -> tuple[str, str]:
    """Map a completeness percentage to a tier + assessment confidence.

    A missing safety triad forces confidence down: even a long README that never
    addresses security, reliability, or oversight cannot be judged with
    confidence, so it can climb no higher than MODERATE / medium.
    """
    if pct >= 70 and triad_covered == 3:
        return "DETAILED", "high"
    if pct >= 45 and triad_covered >= 2:
        return "MODERATE", "medium"
    if pct >= 25:
        return "SPARSE", "low"
    return "MINIMAL", "low"


def assess_completeness(spec, dimensions: list[DimensionScore]) -> InputCompleteness:
    """Assess how complete the input artifact is and what is missing to judge it."""
    text = spec.text
    words = len(_WORD_RE.findall(text))
    headings = len(_HEADING_RE.findall(text))

    # A dimension counts as "evidenced" when the scorers found any support for it.
    evidenced = [d for d in dimensions if d.score > 0.0]
    dim_coverage = len(evidenced) / len(dimensions) if dimensions else 0.0

    triad_scores = {d.name: d.score for d in dimensions if d.name in _SAFETY_TRIAD}
    triad_covered = sum(1 for s in triad_scores.values() if s > 0.0)
    triad_coverage = triad_covered / len(_SAFETY_TRIAD)

    structure = min(1.0, headings / _HEADINGS_FULL)
    length = min(1.0, words / _WORDS_FULL)

    # Weighted blend. Dimension + triad coverage dominate (what we can actually
    # judge); length and structure are supporting signals so a padded-but-empty
    # README cannot buy its way to "detailed".
    factors = {
        "dimension_coverage": round(dim_coverage, 2),
        "safety_triad_coverage": round(triad_coverage, 2),
        "structure": round(structure, 2),
        "length": round(length, 2),
        "words": words,
        "headings": headings,
    }
    blended = (
        0.40 * dim_coverage
        + 0.25 * triad_coverage
        + 0.20 * structure
        + 0.15 * length
    )
    pct = int(round(blended * 100))
    tier, confidence = _tier_and_confidence(pct, triad_covered)

    # Un-evidenced dimensions become the missing-areas list and the questionnaire.
    missing = [d.name for d in dimensions if d.score == 0.0]
    questions = [_QUESTIONS[name] for name in missing if name in _QUESTIONS]

    return InputCompleteness(
        pct=pct,
        tier=tier,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        factors=factors,
        missing_areas=missing,
        clarifying_questions=questions,
    )
