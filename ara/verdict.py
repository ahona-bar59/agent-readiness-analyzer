"""Gate & Verdict engine.

DETERMINISTIC by design (README section 9): the final score and verdict are
computed in plain code from the dimension scores and hard-gate results, never by
an LLM. This is what stops the tool being "talked into" a higher grade.

Two steps:
  1. Evaluate hard gates from the artifact text (detectors below).
  2. Compute the normalised /10 score, then the verdict, applying gate overrides.
"""
from __future__ import annotations

import re

from .rubric import HARD_GATES
from .schema import DimensionScore, HardGate, MAX_TOTAL
from .normalize import AgentSpec


# --------------------------------------------------------------------------- #
# Hard-gate detectors. Each returns (status, evidence).
# Conservative: absence of evidence for a safety control is a FAIL, except where
# the control is genuinely not applicable (e.g. an agent that never writes).
# --------------------------------------------------------------------------- #
def _has(text: str, *phrases: str) -> str | None:
    for p in phrases:
        if p in text:
            return p
    return None


_NO_APPROVAL_RE = re.compile(
    r"(no (human )?(approval|review|oversight)|without (human )?(approval|waiting|review|"
    r"anyone|confirmation)|automatically (appl|fix|deploy|creat|updat|restart|commit)|"
    r"no one has to|nobody has to)",
)


def _gate_guarded_writes(t: str) -> tuple[str, str]:
    writes = _has(t, "write", "persist", "create_", "update_", "delete_", "commit", "deploy")
    if not writes:
        return "PASS", "Agent performs no writes to external systems (nothing to guard)."
    # Strong, unambiguous gating signals win first — these describe an actual guard
    # on the write path, so they are not fooled by "Does NOT write without approval".
    strong = _has(
        t, "after human approval", "only fires after", "tests_approved", "guarded write",
        "blocking gate", "interrupt(", "requires approval", "approval gate",
        "human approves", "after approval",
    )
    if strong:
        return "PASS", f"Writes are gated by an approval step ('{strong}')."
    # Otherwise, explicit "no approval / acts automatically" is a FAIL.
    neg = _NO_APPROVAL_RE.search(t)
    if neg:
        return "FAIL", f"Agent writes autonomously with no approval step ('{neg.group(0)}')."
    if _has(t, "approval", "approved", "confirmation"):
        return "PASS", "Writes appear to involve an approval step."
    return "FAIL", "Agent writes to a real system with no documented approval/guard step."


def _gate_termination(t: str) -> tuple[str, str]:
    bound = _has(
        t, "max retr", "retry_count", "max 2", "best-effort", "always reaches the end",
        "never loops forever", "bounded", "iteration limit", "max iterations", "timeout",
        "max_attempts", "retrypolicy", "retry_policy", "cycle_count", "gen_retry_count",
        "max_gen_retries", "max_revise_iters", "revise_count", "ceiling", "run always",
        "hard ceiling", "cannot spin forever", "cap ",
    )
    if bound:
        return "PASS", f"Execution is bounded ('{bound}')."
    # Only an AUTONOMOUS repetition construct is a concern. A bare "loop" (e.g. a
    # user-triggered "iterative loop", or a linear/sequential pipeline) is not.
    if _has(t, "sequential", "single-parent chain", "linear pipeline"):
        return "PASS", "Linear/sequential pipeline; no autonomous loop."
    if _has(t, "retry", "self-correct", "keeps retrying", "loops until", "until it works", "spin"):
        return "FAIL", "Autonomous retries/loops mentioned but no explicit termination bound documented."
    return "PASS", "No unbounded looping construct described."


def _gate_injection(t: str) -> tuple[str, str]:
    hit = _has(t, "prompt injection", "injection", "jailbreak")
    if hit:
        return "PASS", f"Prompt-injection/jailbreak defense documented ('{hit}')."
    return "FAIL", "No prompt-injection or jailbreak protection documented."


def _gate_self_deploy(t: str) -> tuple[str, str]:
    # Fails only if the text describes the agent changing its OWN autonomy/permissions.
    risky = re.search(
        r"(self[- ]?(deploy|escalat|approv|grant)|grant(s)? itself|"
        r"bypass(es)? (its|the) (own )?(gate|guard|approval)|elevate (its|own) privilege)",
        t,
    )
    if risky:
        # A human-approval qualifier nearby softens it, but default to FAIL.
        return "FAIL", f"Artifact describes self-escalation: '{risky.group(0)}'."
    return "PASS", "No evidence the agent can grant itself autonomy or bypass its gates."


def _gate_safety_screening(t: str) -> tuple[str, str]:
    hit = _has(t, "pii", "content safety", "mask", "redact", "sanitize", "harmful content")
    if hit:
        return "PASS", f"PII/harmful-content handling documented ('{hit}')."
    return "FAIL", "No PII or harmful-content handling described anywhere in the pipeline."


_DETECTORS = {
    "guarded_writes": _gate_guarded_writes,
    "termination_guarantee": _gate_termination,
    "injection_defense": _gate_injection,
    "no_self_deploy": _gate_self_deploy,
    "safety_screening": _gate_safety_screening,
}


def evaluate_gates(spec: AgentSpec) -> list[HardGate]:
    t = spec.lower_text
    gates: list[HardGate] = []
    for gdef in HARD_GATES:
        status, evidence = _DETECTORS[gdef.key](t)
        gates.append(
            HardGate(gate=gdef.key, status=status, evidence=evidence, severity=gdef.severity)
        )
    return gates


# --------------------------------------------------------------------------- #
# Score + verdict
# --------------------------------------------------------------------------- #
def compute_scores(dimensions: list[DimensionScore]) -> tuple[float, float]:
    raw = sum(d.score for d in dimensions)          # out of MAX_TOTAL (16)
    normalised = round(raw / MAX_TOTAL * 10.0, 2)   # out of 10
    return raw, normalised


# --------------------------------------------------------------------------- #
# Prime-dimension cap
# --------------------------------------------------------------------------- #
# Some dimensions are prerequisites for deployment, not just contributors to an
# average. A serious weakness in any of these caps the overall readiness score no
# matter how strong the rest of the card is — you cannot "average away" a missing
# security or reliability story. This is what stops an agent with 0/2 Security
# from landing an 8+/10 on the strength of its other dimensions.
PRIME_DIMENSIONS = ("Security & Safety", "Reliability & Robustness")


def _prime_score_ceiling(
    worst_prime: float, deploy_threshold: float, conditional_threshold: float
) -> float | None:
    """Ceiling on the /10 score given the weakest prime-dimension score (0..2).

    Returns None when no cap applies (prime dimensions are strong). The ladder is
    expressed relative to the configured thresholds so it tracks any override.
    """
    if worst_prime >= 2.0:
        return None                                     # fully covered — no cap
    if worst_prime >= 1.5:
        return round(deploy_threshold + 1.5, 2)         # solid, not flawless
    if worst_prime >= 1.0:
        return round(deploy_threshold - 0.1, 2)         # cannot be "deployable"
    if worst_prime >= 0.5:
        return round(conditional_threshold + 0.9, 2)    # clearly conditional
    return round(conditional_threshold, 2)              # prime dimension ~absent


def apply_prime_dimension_cap(
    normalised: float,
    dimensions: list[DimensionScore],
    *,
    deploy_threshold: float,
    conditional_threshold: float,
) -> tuple[float, list[str]]:
    """Cap the normalised /10 score when a prime dimension scores poorly.

    Returns (possibly-capped score, reasons). A strong showing on secondary
    dimensions must not lift an agent with a weak security or reliability story
    into the deployable range.
    """
    primes = [d for d in dimensions if d.name in PRIME_DIMENSIONS]
    if not primes:
        return normalised, []
    worst = min(primes, key=lambda d: d.score)
    ceiling = _prime_score_ceiling(worst.score, deploy_threshold, conditional_threshold)
    if ceiling is None or normalised <= ceiling:
        return normalised, []
    note = (
        f"PRIME-DIMENSION CAP: '{worst.name}' scored {worst.score}/2, a deployment "
        f"prerequisite. Overall readiness capped at {ceiling}/10 "
        f"(uncapped {normalised}/10) — strength in other dimensions cannot offset a "
        f"weak prime dimension."
    )
    return ceiling, [note]


def compute_verdict(
    total_score: float,
    hard_gates: list[HardGate],
    *,
    strict_gates: bool,
    deploy_threshold: float,
    conditional_threshold: float,
) -> tuple[str, list[str]]:
    """Return (verdict, reasons). Failed hard gates override the score."""
    reasons: list[str] = []
    failed = [g for g in hard_gates if g.status == "FAIL"]
    critical_failed = [g for g in failed if g.severity == "critical"]
    other_failed = [g for g in failed if g.severity != "critical"]

    # 1. A failed CRITICAL gate is catastrophic — force NOT_DEPLOYABLE.
    if strict_gates and critical_failed:
        for g in critical_failed:
            reasons.append(f"CRITICAL GATE FAILED [{g.gate}]: {g.evidence}")
        reasons.append("A failed CRITICAL hard gate forces NOT_DEPLOYABLE regardless of score.")
        return "NOT_DEPLOYABLE", reasons

    if not strict_gates and failed:
        reasons.append(
            f"{len(failed)} hard gate(s) failed but strict-gates is OFF; scored on total only."
        )

    # 2. Base verdict from the normalised score.
    if total_score >= deploy_threshold:
        verdict = "DEPLOYABLE"
    elif total_score >= conditional_threshold:
        verdict = "CONDITIONAL"
    else:
        verdict = "NOT_DEPLOYABLE"
    reasons.append(
        f"Total {total_score}/10 vs thresholds "
        f"(>= {deploy_threshold} deployable, >= {conditional_threshold} conditional)."
    )

    # 3. A failed non-critical (e.g. HIGH) gate can't hard-block, but it caps the
    #    verdict at CONDITIONAL — you can't be "deployable" with an open safety gap.
    if strict_gates and other_failed and verdict == "DEPLOYABLE":
        for g in other_failed:
            reasons.append(f"OPEN [{g.severity}] GATE [{g.gate}]: {g.evidence}")
        reasons.append(
            "An open non-critical safety gate caps the verdict at CONDITIONAL until fixed."
        )
        verdict = "CONDITIONAL"
    return verdict, reasons


# --------------------------------------------------------------------------- #
# Confidence cap — how a vague / undetailed input is handled
# --------------------------------------------------------------------------- #
def apply_confidence_cap(
    verdict: str,
    hard_gates: list["HardGate"],
    completeness,
) -> tuple[str, bool, list[str]]:
    """Adjust the verdict for a low-confidence (sparse) input.

    The score is always computed; this only governs how far it can be *trusted*.
    Two asymmetric moves, both grounded in "absence of evidence is not evidence":

      * A sparse input can never be DEPLOYABLE — the safety evidence needed to
        certify it simply is not present to verify, so DEPLOYABLE is capped to
        CONDITIONAL pending the missing information.
      * A NOT_DEPLOYABLE that is driven purely by a low score (no CRITICAL gate
        firing on a *positively detected* risk) is softened to CONDITIONAL: we
        must not reject an under-documented agent as if it were proven unsafe.

    A CRITICAL gate failure always reflects a risk stated in the text, not a gap,
    so it is never softened — a genuinely dangerous agent stays NOT_DEPLOYABLE
    however sparse the rest of the document is.

    Returns (verdict, provisional, reasons).
    """
    if completeness is None or not completeness.is_low_confidence:
        return verdict, False, []

    reasons = [
        f"ASSESSMENT CONFIDENCE LOW — input is {completeness.tier} "
        f"({completeness.pct}% documentation completeness). The score below is "
        f"PROVISIONAL: it reflects what the artifact documents, not the agent's "
        f"true readiness. Absence of evidence is treated as unverified, not as a "
        f"defect. Answer the clarifying questions to enable a full assessment."
    ]
    critical_failed = [g for g in hard_gates if g.status == "FAIL" and g.severity == "critical"]

    if critical_failed:
        # A real, positively-detected danger overrides sparsity — leave as-is.
        return verdict, True, reasons

    if verdict == "DEPLOYABLE":
        reasons.append(
            "A sparse specification cannot be certified DEPLOYABLE — the safety "
            "evidence required to verify it is not present. Capped at CONDITIONAL "
            "pending the missing information."
        )
        return "CONDITIONAL", True, reasons

    if verdict == "NOT_DEPLOYABLE":
        reasons.append(
            "NOT_DEPLOYABLE here is driven by missing documentation, not by a "
            "detected safety failure. Re-graded to CONDITIONAL (assess-pending): "
            "an under-documented agent must not be rejected as if it were proven "
            "unsafe. Provide the requested detail for a final verdict."
        )
        return "CONDITIONAL", True, reasons

    return verdict, True, reasons


_QUOTED_RE = re.compile(r"'([^']+)'")


def _missing_terms(gaps: list[str]) -> list[str]:
    """Pull the quoted rubric phrases out of gap strings like
    "No explicit evidence of 'prompt injection'." and map them to friendly labels."""
    from .rubric import display_term

    terms: list[str] = []
    for g in gaps:
        m = _QUOTED_RE.search(g)
        if m:
            label = display_term(m.group(1))
            if label not in terms:
                terms.append(label)
    return terms


def _join_terms(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def build_recommendations(
    dimensions: list[DimensionScore], hard_gates: list[HardGate]
) -> list["Recommendation"]:
    """Prioritised, action-oriented recommendations. Failed hard gates come first
    as high-priority fixes (phrased as the control to add); weak dimensions follow
    as medium-priority improvements (phrased as what to document)."""
    from .requirements import GATE_REQUIREMENTS
    from .schema import Recommendation

    recs: list[Recommendation] = []

    # 1. Failed hard gates -> high-priority fixes.
    for g in hard_gates:
        if g.status == "FAIL":
            action = GATE_REQUIREMENTS.get(g.gate) or g.evidence
            priority = "high" if g.severity in ("critical", "high") else "medium"
            recs.append(
                Recommendation(
                    priority=priority,
                    area=g.gate.replace("_", " ").title(),
                    action=action,
                )
            )

    # 2. Weakest dimensions -> improvements, phrased positively.
    for d in sorted(dimensions, key=lambda x: x.score):
        if d.score < 2.0 and d.gaps:
            terms = _missing_terms(d.gaps)
            action = (
                f"Document {_join_terms(terms[:3])}."
                if terms
                else d.gaps[0]
            )
            recs.append(Recommendation(priority="medium", area=d.name, action=action))

    return recs[:12]


def collect_insufficient_evidence(dimensions: list[DimensionScore]) -> list[str]:
    out = []
    for d in dimensions:
        if d.score == 0.0:
            out.append(f"{d.name}: no supporting evidence in the artifact.")
    return out
