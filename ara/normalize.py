"""Ingest & Normalize node.

Turns any artifact (README / spec / code) into a common, minimal Agent Spec the
scorers consume: the cleaned text, a detected agent name, and a detected autonomy
level. When the LLM path is active it can enrich this; the heuristic path relies
on lightweight extraction so the tool works offline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Explicit autonomy DECLARATIONS, checked first. These target a level the author
# is claiming for THIS agent (e.g. "Autonomy Level: L3", "**L2 · Supervised**"),
# not incidental mentions inside an explanation of the L1-L4 ladder.
_AUTONOMY_DECL_RE = re.compile(
    r"autonomy(?:\s*level)?\s*[:\-—·=]\s*\**\s*(l[1-4])\b"     # "Autonomy Level: L3"
    r"|\**\s*(l[1-4])\s*[·—\-\.]\s*(?:supervised|assistive|collaborative|autonomous)"  # "L2 · Supervised"
    r"|autonomy\s*[—\-]\s*(l[1-4])\b",                              # "Autonomy — L3"
    re.IGNORECASE,
)


@dataclass
class AgentSpec:
    agent_name: str
    text: str                       # cleaned (post-guard) text used for scoring
    lower_text: str = ""            # cached lower-cased copy
    autonomy_level: str = "UNKNOWN"
    summary: str = ""               # short "what this agent does" blurb
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.lower_text:
            self.lower_text = self.text.lower()


def _extract_name(text: str, fallback: str) -> str:
    # First markdown H1, else first non-empty line, else fallback.
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        name = m.group(1).strip()
        # Strip trailing acronym in parentheses like "(ARA)".
        return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or fallback
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:80]
    return fallback


# Headings that introduce a "what this agent does" description, e.g.
# "## 1. What It Does", "## Project Overview", "## What this is", "## Summary".
_SUMMARY_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:\d+[\.\)]\s*)?"
    r"(?:what (?:it|this) (?:does|is)|(?:project\s+)?overview|summary|purpose|"
    r"description|about|introduction|mission)\b",
    re.IGNORECASE,
)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
# A bullet or numbered list marker at the start of a line.
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[\.\)])\s+")
# Metadata one-liners we do NOT want as a description (e.g. "Framework: LangGraph").
_METADATA_LINE_RE = re.compile(
    r"(?i)^(framework|status|autonomy|for|structured|version|author|maintainer)\b\s*[:|]"
)


def _clean_summary_line(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^[-*+]\s+", "", s)             # bullet markers
    s = re.sub(r"^>\s?", "", s)                  # blockquote markers
    s = re.sub(r"^\d+[\.\)]\s+", "", s)          # numbered list markers
    s = re.sub(r"`([^`]*)`", r"\1", s)           # inline code
    s = s.replace("**", "").replace("__", "").replace("*", "")
    return s.strip()


def _is_skippable(stripped: str) -> bool:
    return (
        not stripped
        or set(stripped) <= set("-=_")           # horizontal rules
        or stripped.startswith("|")              # table rows
        or stripped.startswith("```")            # code fences
        or stripped.startswith("!")              # images
    )


def _extract_summary(text: str, limit: int = 550) -> str:
    """Pull a short, human-readable description of what the agent does.

    Preference order: an overview-type section, else the first descriptive
    blockquote/paragraph after the title. Returns "" if nothing suitable found.
    """
    lines = text.splitlines()

    def _collect_after(start_idx: int, *, allow_metadata: bool) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        for line in lines[start_idx:]:
            s = line.strip()
            if _ANY_HEADING_RE.match(s):
                break
            if _is_skippable(s):
                continue
            is_list_item = bool(_LIST_MARKER_RE.match(line))
            cleaned = _clean_summary_line(line)
            if not cleaned:
                continue
            if not allow_metadata and _METADATA_LINE_RE.match(cleaned):
                continue
            out.append((cleaned, is_list_item))
            if sum(len(c) + 1 for c, _ in out) > limit:
                break
        return out

    # 1. Overview-type section.
    collected: list[tuple[str, bool]] = []
    for i, line in enumerate(lines):
        if _SUMMARY_HEADING_RE.match(line.strip()):
            collected = _collect_after(i + 1, allow_metadata=True)
            if collected:
                break

    # 2. Fall back to the first descriptive lines after the H1 title.
    if not collected:
        for i, line in enumerate(lines):
            if line.strip().startswith("# "):
                collected = _collect_after(i + 1, allow_metadata=False)
                break

    if not collected:
        return ""
    # Join the fragments back into readable prose. A bullet/numbered item is its
    # own thought, so end it with a period if it lacks terminal punctuation.
    # A wrapped paragraph line is a mid-sentence continuation — join it with a
    # plain space so we don't inject a spurious period ("applies it to. the ...").
    parts: list[str] = []
    for c, is_list_item in collected:
        c = re.sub(r"\s+", " ", c).strip()
        if is_list_item and c and c[-1] not in ".!?:;":
            c += "."
        parts.append(c)
    summary = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(summary) > limit:
        summary = summary[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return summary


# Behavioural signals used to INFER a level when the artifact does not declare one.
# Kept deliberately specific so common words ("adapts", "decides") don't over-promote.
#
# Unambiguous full-autonomy claims — these win outright.
_L4_STRONG_RE = re.compile(
    r"fully autonomous|sets? its own goals|self-?directed|autonomously sets|"
    r"no human (?:approval|oversight|review|involvement|intervention)"
)
_GOAL_RE = re.compile(
    r"goal[-\s]driven|goal[-\s]autonomous|you (?:give|say|set)[^.]{0,20}\bgoal\b|"
    r"finds the tasks|discovers the (?:tasks|work)|figures out how|owns the .how."
)
# A genuine (positive) human-in-the-loop gate. Note we check L4 first so a
# negated phrase like "no human approval" is classified as L4, not HITL.
_HITL_RE = re.compile(
    r"human[-\s]in[-\s]the[-\s]loop|hitl|human (?:approv|review|sign[-\s]?off|"
    r"confirmation)|await_clarification|\binterrupt\b|approval gate|review gate|"
    r"blocking gate|pause[sd]? (?:for|and wait)"
)


def _detect_autonomy(lower_text: str) -> str:
    """Return an autonomy level in {L1, L2, L3, L4}. Never returns UNKNOWN — when
    the artifact gives no signal we fall back to L2 (supervised), the safe
    baseline for an agent that takes a task but is not proven goal-autonomous.

    L1 scripted · L2 task-driven (you give a task) · L3 goal-driven (you give a
    goal, it finds the tasks) · L4 self-directed (sets its own goals).
    """
    # 1. An explicit declaration by the author always wins.
    m = _AUTONOMY_DECL_RE.search(lower_text)
    if m:
        level = next(g for g in m.groups() if g)
        return level.upper()

    # 2. Otherwise infer from described behaviour, most-autonomous first.
    if _L4_STRONG_RE.search(lower_text):
        return "L4"                     # self-directed / no human in the loop
    if _GOAL_RE.search(lower_text):
        return "L3"                     # goal-autonomous, even if writes are gated
    if _HITL_RE.search(lower_text):
        return "L2"                     # task-driven with a human gate
    # No autonomy signal at all -> conservative supervised baseline.
    return "L2"


def normalize(text: str, agent_name: str | None = None) -> AgentSpec:
    name = agent_name or _extract_name(text, "Unnamed Agent")
    lower = text.lower()
    spec = AgentSpec(
        agent_name=name,
        text=text,
        lower_text=lower,
        autonomy_level=_detect_autonomy(lower),
        summary=_extract_summary(text),
    )
    return spec
