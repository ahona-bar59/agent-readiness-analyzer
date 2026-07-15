"""The ARA workflow (README section 6).

Pure-function nodes operate on a shared `state` dict. When `langgraph` is
installed they are wired into a real StateGraph; otherwise the identical nodes
run in sequence. Both paths produce the same Scorecard, so the LangGraph design
is honoured while the tool still runs with zero third-party dependencies.

    Input Guard -> Normalize -> Score (8 dims) -> Hard Gates
                -> Completeness -> Failure Clusters -> Verdict -> Report
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from . import RUBRIC_VERSION
from .config import Settings
from .guards import run_input_guard, GuardResult
from .normalize import normalize
from .scorers import score_all
from .completeness import assess_completeness
from .clustering import detect_clusters
from .llm import build_llm
from .schema import Scorecard
from . import verdict as V


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def node_input_guard(state: dict) -> dict:
    settings: Settings = state["settings"]
    guard: GuardResult = run_input_guard(state["raw_text"], settings.input_token_cap)
    return {"guard": guard, "text": guard.clean_text}


def node_normalize(state: dict) -> dict:
    # Name is extracted from the ORIGINAL text (an agent's title is not PII);
    # scoring uses the guarded/masked text.
    spec = normalize(state["text"], state.get("agent_name"))
    if not state.get("agent_name"):
        from .normalize import _extract_name

        spec.agent_name = _extract_name(state["raw_text"], spec.agent_name)
    return {"spec": spec}


def node_score(state: dict) -> dict:
    return {"dimensions": score_all(state["spec"], state.get("llm"))}


def node_gates(state: dict) -> dict:
    return {"hard_gates": V.evaluate_gates(state["spec"])}


def node_completeness(state: dict) -> dict:
    # How much did the artifact actually give us to judge? Drives assessment
    # confidence, whether the score is provisional, and the clarifying questions.
    return {"completeness": assess_completeness(state["spec"], state["dimensions"])}


def node_clusters(state: dict) -> dict:
    return {"failure_clusters": detect_clusters(state["dimensions"])}


def node_verdict(state: dict) -> dict:
    settings: Settings = state["settings"]
    raw, total = V.compute_scores(state["dimensions"])
    # A weak prime dimension (Security / Reliability) caps the overall score
    # before the verdict is decided — see verdict.apply_prime_dimension_cap.
    total, cap_reasons = V.apply_prime_dimension_cap(
        total,
        state["dimensions"],
        deploy_threshold=settings.deploy_threshold,
        conditional_threshold=settings.conditional_threshold,
    )
    verdict, reasons = V.compute_verdict(
        total,
        state["hard_gates"],
        strict_gates=settings.strict_gates,
        deploy_threshold=settings.deploy_threshold,
        conditional_threshold=settings.conditional_threshold,
    )
    # A vague / under-documented input can be scored but not fully trusted: cap or
    # soften the verdict and flag it provisional. Real red flags survive this.
    completeness = state.get("completeness")
    verdict, provisional, conf_reasons = V.apply_confidence_cap(
        verdict, state["hard_gates"], completeness
    )
    reasons = conf_reasons + cap_reasons + reasons
    return {
        "raw_score": raw,
        "total_score": total,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "provisional": provisional,
        "assessment_confidence": completeness.confidence if completeness else "high",
        "recommendations": V.build_recommendations(state["dimensions"], state["hard_gates"]),
        "insufficient_evidence": V.collect_insufficient_evidence(state["dimensions"]),
    }


def node_report(state: dict) -> dict:
    settings: Settings = state["settings"]
    spec = state["spec"]
    card = Scorecard(
        agent_name=spec.agent_name,
        rubric_version=settings.rubric_version or RUBRIC_VERSION,
        analyzed_at=state["analyzed_at"],
        scoring_mode=settings.scoring_mode,
        agent_summary=getattr(spec, "summary", ""),
        assessment_confidence=state.get("assessment_confidence", "high"),
        provisional=state.get("provisional", False),
        completeness=state.get("completeness"),
        total_score=state["total_score"],
        raw_score=state["raw_score"],
        verdict=state["verdict"],
        autonomy_level=spec.autonomy_level,
        dimensions=state["dimensions"],
        hard_gates=state["hard_gates"],
        failure_clusters=state["failure_clusters"],
        recommendations=state["recommendations"],
        insufficient_evidence=state["insufficient_evidence"],
    )
    card.validate()
    return {"scorecard": card}


_NODE_SEQUENCE = [
    node_input_guard,
    node_normalize,
    node_score,
    node_gates,
    node_completeness,
    node_clusters,
    node_verdict,
    node_report,
]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _run_sequential(state: dict) -> dict:
    for node in _NODE_SEQUENCE:
        state.update(node(state))
    return state


class _ARAState(TypedDict, total=False):
    raw_text: str
    settings: Any
    agent_name: str
    llm: Any
    analyzed_at: str
    guard: Any
    text: str
    spec: Any
    dimensions: list
    hard_gates: list
    completeness: Any
    failure_clusters: list
    raw_score: float
    total_score: float
    verdict: str
    verdict_reasons: list
    provisional: bool
    assessment_confidence: str
    recommendations: list
    insufficient_evidence: list
    scorecard: Any


def _run_langgraph(state: dict) -> dict:
    """Wire the same nodes into a real LangGraph StateGraph if available."""
    try:
        from langgraph.graph import StateGraph, START, END  # type: ignore
    except ImportError:
        return _run_sequential(state)

    g = StateGraph(_ARAState)
    names = [
        "input_guard", "normalize", "score", "gates",
        "completeness", "clusters", "verdict", "report",
    ]
    for name, fn in zip(names, _NODE_SEQUENCE):
        g.add_node(name, fn)
    g.add_edge(START, names[0])
    for a, b in zip(names, names[1:]):
        g.add_edge(a, b)
    g.add_edge(names[-1], END)
    compiled = g.compile()
    return compiled.invoke(state)


def analyze(
    raw_text: str,
    settings: Settings,
    *,
    agent_name: str | None = None,
    analyzed_at: str | None = None,
    use_langgraph: bool = True,
):
    """Run the full ARA pipeline. Returns (Scorecard, verdict_reasons, GuardResult)."""
    llm = build_llm(settings, role="scorer")
    state: dict = {
        "raw_text": raw_text,
        "settings": settings,
        "agent_name": agent_name,
        "llm": llm,
        "analyzed_at": analyzed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    state = _run_langgraph(state) if use_langgraph else _run_sequential(state)
    return state["scorecard"], state["verdict_reasons"], state["guard"]
