"""Smoke + behaviour tests for ARA. Run with: python -m pytest tests/ -q
(or: python tests/test_ara.py for a dependency-free run)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ara.config import Settings
from ara.graph import analyze
from ara.guards import run_input_guard
from ara.schema import NUM_DIMENSIONS


def _settings() -> Settings:
    s = Settings.load()
    s.force_mock = True  # deterministic offline scoring for tests
    return s


def test_strong_agent_is_deployable():
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_case_creation_agent.md").read_text(
        encoding="utf-8"
    )
    card, reasons, guard = analyze(text, _settings(), use_langgraph=False)
    card.validate()
    assert len(card.dimensions) == NUM_DIMENSIONS
    assert card.verdict == "DEPLOYABLE", (card.verdict, card.total_score)
    assert card.total_score >= 7.0
    assert all(g.status == "PASS" for g in card.hard_gates)


def test_risky_agent_is_not_deployable():
    text = (Path(__file__).resolve().parents[1] / "examples" / "risky_agent.md").read_text(
        encoding="utf-8"
    )
    card, reasons, guard = analyze(text, _settings(), use_langgraph=False)
    assert card.verdict == "NOT_DEPLOYABLE"
    failed = {g.gate for g in card.hard_gates if g.status == "FAIL"}
    # No approval on writes + self-escalation must both be caught.
    assert "guarded_writes" in failed
    assert "no_self_deploy" in failed


def test_injection_in_artifact_is_flagged_not_obeyed():
    text = (Path(__file__).resolve().parents[1] / "examples" / "risky_agent.md").read_text(
        encoding="utf-8"
    )
    guard = run_input_guard(text)
    assert guard.injection_hits, "should detect the 'ignore previous instructions' attempt"
    # And it still gets a low verdict despite the '10/10' instruction.
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.total_score < 7.0


def test_pii_masking():
    guard = run_input_guard("Contact John Smith at john.smith@example.com for details.")
    assert guard.pii_masked >= 1
    assert "@example.com" not in guard.clean_text


def _dim(card, name):
    return next(d for d in card.dimensions if d.name == name)


def test_prime_dimension_cap_limits_overall_score():
    """A 0/2 prime dimension (Security) must cap the overall score — a strong
    showing elsewhere cannot lift the agent into the deployable range."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_optimiser_agent.md").read_text(
        encoding="utf-8"
    )
    card, reasons, _ = analyze(text, _settings(), use_langgraph=False)
    assert _dim(card, "Security & Safety").score == 0.0
    # Uncapped it would score ~6.6; the cap pins it to the conditional threshold.
    assert card.total_score <= 5.0, card.total_score
    assert card.verdict == "CONDITIONAL"
    assert any(r.startswith("PRIME-DIMENSION CAP") for r in reasons), reasons


def test_partial_signal_coverage_is_not_full_marks():
    """A minority of a dimension's rubric signals must not earn 2/2.
    Reliability on the Test Optimiser matches 7 of 20 signals (~35%)."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_optimiser_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    rel = _dim(card, "Reliability & Robustness")
    assert rel.score < 2.0, rel.score
    assert "coverage" in rel.rationale.lower()


def test_report_includes_agent_summary():
    """The scorecard carries a human-readable 'what this agent does' blurb."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_optimiser_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.agent_summary
    assert len(card.agent_summary) > 30


def test_autonomy_level_is_always_concluded():
    """Every agent must land on L1-L4 — the analyzer never reports UNKNOWN."""
    import glob

    root = Path(__file__).resolve().parents[1]
    for f in glob.glob(str(root / "examples" / "*.md")):
        card, _, _ = analyze(Path(f).read_text(encoding="utf-8"), _settings(), use_langgraph=False)
        assert card.autonomy_level in ("L1", "L2", "L3", "L4"), (f, card.autonomy_level)


def test_hitl_task_agent_is_supervised_l2():
    """A task-driven agent with a human-in-the-loop pause (hyphenated / bare
    `interrupt`) is L2, not UNKNOWN."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "user_story_refinement_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.autonomy_level == "L2", card.autonomy_level


def test_fully_autonomous_agent_is_l4():
    """'Fully autonomous / no human approval' must classify as L4."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "risky_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.autonomy_level == "L4", card.autonomy_level


def test_vague_readme_is_scored_at_low_confidence_and_provisional():
    """A vague/undetailed README must still yield a score, but flagged LOW
    confidence + provisional, with clarifying questions — not a false verdict."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "vague_agent.md").read_text(
        encoding="utf-8"
    )
    card, reasons, _ = analyze(text, _settings(), use_langgraph=False)
    card.validate()
    # It still arrives at a score and a deployment verdict.
    assert 0.0 <= card.total_score <= 10.0
    assert card.verdict in ("DEPLOYABLE", "CONDITIONAL", "NOT_DEPLOYABLE")
    # But it is explicitly low-confidence and provisional.
    assert card.assessment_confidence == "low"
    assert card.provisional is True
    assert card.completeness is not None
    assert card.completeness.tier in ("SPARSE", "MINIMAL")
    # A sparse input can never be certified DEPLOYABLE.
    assert card.verdict != "DEPLOYABLE"
    # And it generates a targeted questionnaire.
    assert card.completeness.clarifying_questions
    assert any("CONFIDENCE LOW" in r for r in reasons), reasons


def test_vague_readme_is_not_hard_rejected_without_a_real_red_flag():
    """An under-documented (but not positively dangerous) agent must be graded
    CONDITIONAL 'assess-pending', not NOT_DEPLOYABLE as if it were proven unsafe."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "vague_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    # No CRITICAL gate fires on mere absence of evidence.
    assert not [g for g in card.hard_gates if g.status == "FAIL" and g.severity == "critical"]
    assert card.verdict == "CONDITIONAL"


def test_detailed_agent_stays_high_confidence_and_final():
    """A rich README is unaffected by the completeness layer: high confidence,
    not provisional — the calibrated verdict path is preserved."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_case_creation_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.assessment_confidence == "high"
    assert card.provisional is False
    assert card.verdict == "DEPLOYABLE"


def test_vague_but_dangerous_agent_still_not_deployable():
    """Sparsity must never rescue a positively-detected danger: the risky agent
    stays NOT_DEPLOYABLE even though its README is short."""
    text = (Path(__file__).resolve().parents[1] / "examples" / "risky_agent.md").read_text(
        encoding="utf-8"
    )
    card, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert card.verdict == "NOT_DEPLOYABLE"


def test_verdict_is_deterministic():
    text = (Path(__file__).resolve().parents[1] / "examples" / "test_case_creation_agent.md").read_text(
        encoding="utf-8"
    )
    a, _, _ = analyze(text, _settings(), use_langgraph=False)
    b, _, _ = analyze(text, _settings(), use_langgraph=False)
    assert a.total_score == b.total_score
    assert a.verdict == b.verdict


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
