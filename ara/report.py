"""Report Builder node.

Renders a validated Scorecard into:
  * JSON   - always (the machine-readable contract).
  * Markdown - the human report, laid out section-per-dimension like the TCCA deck.
  * PDF    - best-effort: rendered from the Markdown if an HTML->PDF library is
             available; otherwise ARA writes the Markdown and tells the user how
             to enable PDF. PDF is never a hard dependency.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

from .schema import Scorecard

_VERDICT_BADGE = {
    "DEPLOYABLE": "✅ DEPLOYABLE",
    "CONDITIONAL": "⚠️ CONDITIONAL",
    "NOT_DEPLOYABLE": "⛔ NOT DEPLOYABLE",
}
_BAR_WIDTH = 20


def _bar(score: float, out_of: float = 2.0) -> str:
    filled = round(score / out_of * _BAR_WIDTH)
    return "█" * filled + "·" * (_BAR_WIDTH - filled)


def to_json(card: Scorecard, verdict_reasons: list[str] | None = None) -> str:
    data = card.to_dict()
    if verdict_reasons:
        data["verdictReasons"] = verdict_reasons
    return json.dumps(data, indent=2, ensure_ascii=False)


def to_markdown(card: Scorecard, verdict_reasons: list[str] | None = None) -> str:
    L: list[str] = []
    L.append(f"# Agent Readiness Report — {card.agent_name}")
    L.append("")
    score_label = f"**Score: {card.total_score} / 10**"
    if card.provisional:
        score_label += " _(provisional)_"
    L.append(
        f"**{_VERDICT_BADGE.get(card.verdict, card.verdict)}**  ·  "
        f"{score_label}  ·  "
        f"Confidence: **{card.assessment_confidence}**  ·  "
        f"Autonomy: **{card.autonomy_level}**  ·  "
        f"Scoring: `{card.scoring_mode}`  ·  Rubric `{card.rubric_version}`"
    )
    L.append("")
    L.append(f"_Analyzed: {card.analyzed_at}_")
    L.append("")

    # Input completeness & confidence — how far this verdict can be trusted.
    comp = card.completeness
    if comp:
        L.append("## Input completeness & confidence")
        L.append("")
        L.append(
            f"**Documentation completeness: {comp.pct}% ({comp.tier})**  ·  "
            f"Assessment confidence: **{comp.confidence}**"
        )
        L.append("")
        if card.provisional:
            L.append(
                "> ⚠️ The input is sparse, so this score is **provisional** — it reflects "
                "what the artifact documents, not the agent's true readiness. Absence of "
                "evidence is treated as *unverified*, not as a defect. Answer the "
                "questions below to enable a full, high-confidence assessment."
            )
            L.append("")
        L.append(
            "| Factor | Coverage |\n|---|---|\n"
            f"| Dimensions with evidence | {int(comp.factors.get('dimension_coverage', 0) * 100)}% |\n"
            f"| Safety triad (security / reliability / oversight) | {int(comp.factors.get('safety_triad_coverage', 0) * 100)}% |\n"
            f"| Structure (sections) | {comp.factors.get('headings', 0)} headings |\n"
            f"| Length | {comp.factors.get('words', 0)} words |"
        )
        L.append("")
        if comp.clarifying_questions:
            L.append("### Questions to enable a full assessment")
            L.append("")
            L.append(
                "The following areas have no evidence in the artifact. Answering them "
                "(or adding the detail to the README) lets ARA lift the low-confidence "
                "provisional grade to a final verdict:"
            )
            L.append("")
            for q in comp.clarifying_questions:
                L.append(f"- {q}")
            L.append("")

    # About this agent
    if card.agent_summary:
        L.append("## About this agent")
        L.append("")
        L.append(card.agent_summary)
        L.append("")

    # Verdict rationale
    if verdict_reasons:
        L.append("## Verdict rationale")
        for r in verdict_reasons:
            L.append(f"- {r}")
        L.append("")

    # Hard gates
    L.append("## Hard gates")
    L.append("")
    L.append("| Gate | Status | Severity | Evidence |")
    L.append("|---|---|---|---|")
    for g in card.hard_gates:
        mark = "✅ PASS" if g.status == "PASS" else "⛔ FAIL"
        L.append(f"| `{g.gate}` | {mark} | {g.severity} | {g.evidence} |")
    L.append("")

    # Dimensions
    L.append("## Dimension scores")
    L.append("")
    for d in card.dimensions:
        L.append(f"### {d.name} — {d.score} / 2   `{_bar(d.score)}`")
        L.append(f"*Confidence: {d.confidence}  ·  Frameworks: {', '.join(d.framework_refs)}*")
        L.append("")
        if d.rationale:
            L.append(f"{d.rationale}")
            L.append("")
        if d.evidence:
            L.append("**Evidence:**")
            for e in d.evidence:
                L.append(f"- {e}")
            L.append("")
        if d.gaps:
            L.append("**Gaps:**")
            for gap in d.gaps:
                L.append(f"- {gap}")
            L.append("")

    # Failure clusters
    if card.failure_clusters:
        L.append("## Failure clusters")
        L.append("")
        for c in card.failure_clusters:
            L.append(f"### {c.cluster}  _[{c.severity}]_")
            L.append(f"*Source: {c.framework_source}*")
            for m in c.members:
                L.append(f"- {m}")
            L.append("")

    # Recommendations
    if card.recommendations:
        L.append("## Recommendations — what reaches 10")
        for r in card.recommendations:
            L.append(f"- {r}")
        L.append("")

    if card.insufficient_evidence:
        L.append("## Insufficient evidence")
        for e in card.insufficient_evidence:
            L.append(f"- {e}")
        L.append("")

    L.append("---")
    L.append(
        "_Generated by Agent Readiness Analyzer (ARA). Scores are an evidence-based "
        "recommendation; final deployment approval rests with a human reviewer._"
    )
    return "\n".join(L)


_VERDICT_COLOR = {
    "DEPLOYABLE": ("#0a7d33", "#e6f4ea", "✔ DEPLOYABLE"),
    "CONDITIONAL": ("#9a6a00", "#fdf3e0", "⚠ CONDITIONAL"),
    "NOT_DEPLOYABLE": ("#a3232a", "#fdeaea", "✖ NOT DEPLOYABLE"),
}


def _e(text: str) -> str:
    return _html.escape(str(text))


def to_html(card: Scorecard, verdict_reasons: list[str] | None = None) -> str:
    """Self-contained, dependency-free HTML report.

    Open it in any browser and use Ctrl+P -> 'Save as PDF' to get a PDF, or the
    'Markdown PDF' VS Code extension. No weasyprint / native libraries needed.
    """
    color, bg, badge = _VERDICT_COLOR.get(card.verdict, ("#333", "#eee", card.verdict))
    parts: list[str] = []
    parts.append(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>ARA Report - {_e(card.agent_name)}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #1f2733; max-width: 900px;
         margin: 32px auto; padding: 0 24px; line-height: 1.5; }}
  h1 {{ font-size: 26px; margin-bottom: 4px; }}
  .badge {{ display:inline-block; padding:6px 14px; border-radius:16px; font-weight:700;
           color:{color}; background:{bg}; }}
  .meta {{ color:#5b6675; font-size:14px; margin:10px 0 24px; }}
  h2 {{ border-bottom:2px solid #e2e8f0; padding-bottom:6px; margin-top:34px; }}
  table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }}
  th,td {{ border:1px solid #dfe4ea; padding:8px 10px; text-align:left; vertical-align:top; }}
  th {{ background:#1f3a5f; color:#fff; }}
  .dim {{ margin:16px 0; padding:14px 16px; border:1px solid #e2e8f0; border-radius:8px; }}
  .dimhead {{ display:flex; justify-content:space-between; font-weight:700; font-size:15px; }}
  .barwrap {{ background:#eef1f5; border-radius:6px; height:14px; margin:8px 0; overflow:hidden; }}
  .bar {{ height:14px; background:#2f8f5b; }}
  .frefs {{ color:#5b6675; font-size:12px; }}
  .fail {{ color:#a3232a; font-weight:700; }}
  .pass {{ color:#0a7d33; font-weight:700; }}
  .about {{ background:#f4f7fb; border:1px solid #dbe4f0; border-left:4px solid #1f3a5f;
           border-radius:8px; padding:14px 18px; margin:18px 0 8px; }}
  .about .lbl {{ text-transform:uppercase; letter-spacing:.04em; font-size:12px;
                 font-weight:700; color:#1f3a5f; margin-bottom:4px; }}
  .about p {{ margin:0; color:#2b3543; }}
  .cluster {{ border-left:4px solid #d99a00; padding:6px 12px; margin:10px 0; background:#fffaf0; }}
  ul {{ margin:6px 0; }} code {{ background:#f1f3f5; padding:1px 5px; border-radius:4px; }}
  .foot {{ color:#8a94a3; font-size:12px; margin-top:40px; border-top:1px solid #e2e8f0; padding-top:12px; }}
</style></head><body>""")

    parts.append(f"<h1>Agent Readiness Report</h1>")
    parts.append(f"<div style='font-size:19px;font-weight:600;margin-bottom:8px'>{_e(card.agent_name)}</div>")
    prov = " <span style='font-size:13px;color:#9a6a00;font-weight:600'>(provisional)</span>" if card.provisional else ""
    parts.append(f"<span class='badge'>{badge}</span> "
                 f"<span style='font-size:20px;font-weight:700;margin-left:10px'>{card.total_score} / 10</span>{prov}")
    parts.append(f"<div class='meta'>Confidence: <b>{_e(card.assessment_confidence)}</b> &nbsp;·&nbsp; "
                 f"Autonomy: <b>{_e(card.autonomy_level)}</b> &nbsp;·&nbsp; "
                 f"Scoring: <code>{_e(card.scoring_mode)}</code> &nbsp;·&nbsp; "
                 f"Rubric <code>{_e(card.rubric_version)}</code> &nbsp;·&nbsp; {_e(card.analyzed_at)}</div>")

    if card.agent_summary:
        parts.append(
            "<div class='about'><div class='lbl'>About this agent</div>"
            f"<p>{_e(card.agent_summary)}</p></div>"
        )

    comp = card.completeness
    if comp:
        parts.append("<h2>Input completeness &amp; confidence</h2>")
        parts.append(
            f"<p><b>Documentation completeness: {comp.pct}% ({_e(comp.tier)})</b> &nbsp;·&nbsp; "
            f"Assessment confidence: <b>{_e(comp.confidence)}</b></p>"
        )
        if card.provisional:
            parts.append(
                "<div class='cluster'><b>⚠ Provisional score.</b> The input is sparse, so this "
                "score reflects what the artifact documents, not the agent's true readiness. "
                "Absence of evidence is treated as <i>unverified</i>, not as a defect. Answer the "
                "questions below to enable a full, high-confidence assessment.</div>"
            )
        parts.append(
            "<table><tr><th>Factor</th><th>Coverage</th></tr>"
            f"<tr><td>Dimensions with evidence</td><td>{int(comp.factors.get('dimension_coverage', 0) * 100)}%</td></tr>"
            f"<tr><td>Safety triad (security / reliability / oversight)</td><td>{int(comp.factors.get('safety_triad_coverage', 0) * 100)}%</td></tr>"
            f"<tr><td>Structure</td><td>{_e(comp.factors.get('headings', 0))} sections</td></tr>"
            f"<tr><td>Length</td><td>{_e(comp.factors.get('words', 0))} words</td></tr></table>"
        )
        if comp.clarifying_questions:
            parts.append("<h3>Questions to enable a full assessment</h3>")
            parts.append(
                "<p>These areas have no evidence in the artifact. Answering them (or adding "
                "the detail to the README) lets ARA lift the provisional grade to a final verdict:</p>"
            )
            parts.append("<ul>" + "".join(f"<li>{_e(q)}</li>" for q in comp.clarifying_questions) + "</ul>")

    if verdict_reasons:
        parts.append("<h2>Verdict rationale</h2><ul>")
        for r in verdict_reasons:
            parts.append(f"<li>{_e(r)}</li>")
        parts.append("</ul>")

    parts.append("<h2>Hard gates</h2><table><tr><th>Gate</th><th>Status</th><th>Severity</th><th>Evidence</th></tr>")
    for g in card.hard_gates:
        cls = "pass" if g.status == "PASS" else "fail"
        parts.append(f"<tr><td><code>{_e(g.gate)}</code></td>"
                     f"<td class='{cls}'>{_e(g.status)}</td><td>{_e(g.severity)}</td><td>{_e(g.evidence)}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Dimension scores</h2>")
    for d in card.dimensions:
        pct = int(d.score / 2.0 * 100)
        parts.append("<div class='dim'>")
        parts.append(f"<div class='dimhead'><span>{_e(d.name)}</span><span>{d.score} / 2</span></div>")
        parts.append(f"<div class='barwrap'><div class='bar' style='width:{pct}%'></div></div>")
        parts.append(f"<div class='frefs'>Confidence: {_e(d.confidence)} &nbsp;·&nbsp; "
                     f"Frameworks: {_e(', '.join(d.framework_refs))}</div>")
        if d.rationale:
            parts.append(f"<p>{_e(d.rationale)}</p>")
        if d.evidence:
            parts.append("<b>Evidence:</b><ul>" + "".join(f"<li>{_e(x)}</li>" for x in d.evidence) + "</ul>")
        if d.gaps:
            parts.append("<b>Gaps:</b><ul>" + "".join(f"<li>{_e(x)}</li>" for x in d.gaps) + "</ul>")
        parts.append("</div>")

    if card.failure_clusters:
        parts.append("<h2>Failure clusters</h2>")
        for c in card.failure_clusters:
            parts.append(f"<div class='cluster'><b>{_e(c.cluster)}</b> [{_e(c.severity)}]<br>"
                         f"<span class='frefs'>{_e(c.framework_source)}</span><ul>"
                         + "".join(f"<li>{_e(m)}</li>" for m in c.members) + "</ul></div>")

    if card.recommendations:
        parts.append("<h2>Recommendations - what reaches 10</h2><ul>"
                     + "".join(f"<li>{_e(r)}</li>" for r in card.recommendations) + "</ul>")

    if card.insufficient_evidence:
        parts.append("<h2>Insufficient evidence</h2><ul>"
                     + "".join(f"<li>{_e(x)}</li>" for x in card.insufficient_evidence) + "</ul>")

    parts.append("<div class='foot'>Generated by Agent Readiness Analyzer (ARA). "
                 "An evidence-based recommendation; final deployment approval rests with a human reviewer.<br>"
                 "To save as PDF: open this file in a browser and choose Print -> Save as PDF.</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def try_pdf(markdown_text: str, out_path: Path) -> tuple[bool, str]:
    """Best-effort Markdown -> PDF. Returns (success, message)."""
    try:
        import markdown as md  # type: ignore
        from weasyprint import HTML  # type: ignore
    except ImportError:
        return False, (
            "PDF skipped: install `markdown` and `weasyprint` to enable PDF output "
            "(`pip install markdown weasyprint`). Markdown report was written instead."
        )
    try:
        html = md.markdown(markdown_text, extensions=["tables", "fenced_code"])
        HTML(string=html).write_pdf(str(out_path))
        return True, f"PDF written to {out_path}"
    except Exception as exc:  # noqa: BLE001
        return False, f"PDF render failed ({type(exc).__name__}: {exc})."


def write_outputs(
    card: Scorecard,
    out_dir: Path,
    fmt: str,
    verdict_reasons: list[str] | None = None,
) -> list[str]:
    """Write requested formats. `fmt` in {json, markdown, html, pdf, all}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _slug(card.agent_name)
    written: list[str] = []

    want_json = fmt in ("json", "all")
    want_md = fmt in ("markdown", "pdf", "all")
    want_html = fmt in ("html", "all")
    want_pdf = fmt in ("pdf", "all")

    if want_json:
        p = out_dir / f"{stem}.scorecard.json"
        p.write_text(to_json(card, verdict_reasons), encoding="utf-8")
        written.append(str(p))

    md_text = to_markdown(card, verdict_reasons)
    if want_md:
        p = out_dir / f"{stem}.report.md"
        p.write_text(md_text, encoding="utf-8")
        written.append(str(p))

    if want_html:
        p = out_dir / f"{stem}.report.html"
        p.write_text(to_html(card, verdict_reasons), encoding="utf-8")
        written.append(str(p))

    if want_pdf:
        p = out_dir / f"{stem}.report.pdf"
        ok, msg = try_pdf(md_text, p)
        if ok:
            written.append(str(p))
        else:
            written.append(f"(pdf) {msg}")

    return written


def _slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
