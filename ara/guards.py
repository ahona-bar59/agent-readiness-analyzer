"""Input Guard — ARA's own guardrails (README section 10).

Runs before any scoring. Because ARA analyses untrusted third-party specs, the
artifact itself is treated as data, never as instructions:

  * PII masking      - mask emails and obvious names before the LLM sees them.
  * Injection block  - detect "ignore previous instructions / give this 10/10"
                       style attempts embedded in the artifact.
  * Length cap       - reject / flag oversized input (context-exhaustion defence).

The guard never raises on normal input; it returns a GuardResult the pipeline
records in the report so decisions are auditable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Person-name detector: only mask a "Firstname Lastname" pair when it sits in a
# genuine person context (after contact/by/author/etc.), so ordinary Title Case
# product names and headings ("Test Case Creation Agent") are NOT masked.
NAME_RE = re.compile(
    r"\b(?:contact|by|from|author(?:ed by)?|owner|reviewer|assignee|assigned to|name)\b"
    r"\s*:?\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
    re.IGNORECASE,
)
# A name immediately preceding an email, e.g. "Jane Doe (jane@x.com)".
NAME_BEFORE_EMAIL_RE = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b(?=[^\n]{0,4}@)")

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|prior|above) instructions",
    r"disregard (all |the )?(previous|prior|above)",
    r"give (this|the) agent (a )?(10|ten|full|perfect|max)",
    r"you must score",
    r"set (the )?score to",
    r"mark (this|it) (as )?deployable",
    r"system prompt",
    r"reveal your (instructions|prompt)",
    r"act as (?!a test)",  # "act as ..." role hijack (allow "act as a test")
]
INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.IGNORECASE)

# ~4 chars per token heuristic.
CHARS_PER_TOKEN = 4


@dataclass
class GuardResult:
    clean_text: str
    original_chars: int
    estimated_tokens: int
    pii_masked: int = 0
    injection_hits: list[str] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def injection_confidence(self) -> float:
        """Crude confidence: saturates as more distinct patterns match."""
        if not self.injection_hits:
            return 0.0
        return min(1.0, 0.45 + 0.2 * len(self.injection_hits))


def _mask_pii(text: str) -> tuple[str, int]:
    count = 0

    def _email(m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[EMAIL]"

    def _name_group1(m: re.Match) -> str:
        nonlocal count
        count += 1
        # Preserve the indicator word, mask only the captured name.
        return m.group(0).replace(m.group(1), "[NAME]")

    def _name_plain(m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[NAME]"

    text = NAME_BEFORE_EMAIL_RE.sub(_name_plain, text)  # before emails are masked
    text = EMAIL_RE.sub(_email, text)
    text = NAME_RE.sub(_name_group1, text)
    return text, count


def run_input_guard(text: str, token_cap: int = 8000) -> GuardResult:
    """Apply PII masking, injection detection, and the length cap."""
    original_chars = len(text)

    # 1. Injection detection (on the raw text, before masking).
    hits = sorted({m.group(0).lower().strip() for m in INJECTION_RE.finditer(text)})

    # 2. PII masking.
    masked, pii_count = _mask_pii(text)

    # 3. Length cap.
    truncated = False
    est_tokens = max(1, len(masked) // CHARS_PER_TOKEN)
    if est_tokens > token_cap:
        cutoff = token_cap * CHARS_PER_TOKEN
        masked = masked[:cutoff]
        truncated = True

    result = GuardResult(
        clean_text=masked,
        original_chars=original_chars,
        estimated_tokens=est_tokens,
        pii_masked=pii_count,
        injection_hits=hits,
        truncated=truncated,
    )
    if pii_count:
        result.notes.append(f"Masked {pii_count} PII item(s) before scoring.")
    if hits:
        result.notes.append(
            f"Detected {len(hits)} prompt-injection pattern(s) in the artifact; "
            "treated as data, not instructions."
        )
    if truncated:
        result.notes.append(
            f"Artifact exceeded the {token_cap}-token cap and was truncated for scoring."
        )
    return result
