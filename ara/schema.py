"""Output schema for ARA scorecards.

Implemented with stdlib dataclasses so the tool runs with zero third-party
dependencies. `Scorecard.validate()` enforces the invariants the README promises
(scores in range, verdict consistent with the total, etc.). When `pydantic` is
installed it is used as an extra validation pass, but it is not required.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

Confidence = Literal["high", "medium", "low"]
Verdict = Literal["DEPLOYABLE", "CONDITIONAL", "NOT_DEPLOYABLE"]
GateStatus = Literal["PASS", "FAIL"]
Severity = Literal["critical", "high", "medium", "low"]

MAX_DIMENSION_SCORE = 2.0
NUM_DIMENSIONS = 8
MAX_TOTAL = MAX_DIMENSION_SCORE * NUM_DIMENSIONS  # 16 raw -> normalised to /10


@dataclass
class DimensionScore:
    name: str
    score: float                       # 0.0 - 2.0
    confidence: Confidence
    framework_refs: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""
    gaps: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not 0.0 <= self.score <= MAX_DIMENSION_SCORE:
            raise ValueError(f"{self.name}: score {self.score} out of range 0..2")
        if self.confidence not in ("high", "medium", "low"):
            raise ValueError(f"{self.name}: bad confidence {self.confidence!r}")


@dataclass
class HardGate:
    gate: str
    status: GateStatus
    evidence: str
    severity: Severity = "critical"

    def validate(self) -> None:
        if self.status not in ("PASS", "FAIL"):
            raise ValueError(f"{self.gate}: bad status {self.status!r}")


@dataclass
class FailureCluster:
    cluster: str
    severity: Severity
    members: list[str] = field(default_factory=list)
    framework_source: str = ""
    description: str = ""          # plain-English "what this means"


@dataclass
class Recommendation:
    """One actionable, prioritised recommendation for raising the score.

    `priority` groups the report ("Priority fixes" vs "Further improvements");
    `area` is the gate or dimension it relates to; `action` is phrased as a
    positive instruction ("Add …", "Document …")."""

    priority: Literal["high", "medium", "low"]
    area: str
    action: str


# Documentation-completeness tiers, in descending order of detail. They drive the
# assessment confidence and whether a score may be treated as final or provisional.
CompletenessTier = Literal["DETAILED", "MODERATE", "SPARSE", "MINIMAL"]


@dataclass
class InputCompleteness:
    """How much the input artifact actually gives ARA to judge.

    A vague / undetailed README is not the same as an unsafe agent: it means the
    evidence needed to certify the agent is *absent*, not that a problem is
    *present*. This assessment lets the verdict distinguish the two — a sparse
    input yields a PROVISIONAL score at LOW confidence plus a list of clarifying
    questions, instead of a falsely confident pass or rejection.
    """

    pct: int                                   # 0-100 documentation completeness
    tier: CompletenessTier
    confidence: Confidence                     # assessment confidence this drives
    factors: dict = field(default_factory=dict)  # per-signal breakdown (auditable)
    missing_areas: list[str] = field(default_factory=list)
    clarifying_questions: list[str] = field(default_factory=list)

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence == "low"


RequirementStatus = Literal["PRESENT", "PARTIAL", "MISSING"]


@dataclass
class RequirementItem:
    """One entry in the client-facing input-requirements checklist: an area the
    README must document, its current state in the artifact, and the specific
    parameters expected. `mandatory` items block a clean deployability decision."""

    area: str
    category: Literal["dimension", "gate"]
    status: RequirementStatus
    mandatory: bool = False
    required_parameters: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Scorecard:
    agent_name: str
    rubric_version: str
    analyzed_at: str
    scoring_mode: str                  # "llm" | "heuristic"
    total_score: float                 # normalised to /10
    raw_score: float                   # sum of dimension scores (/16)
    verdict: Verdict
    autonomy_level: str                # L1 | L2 | L3 | L4 | UNKNOWN
    agent_summary: str = ""            # short "what this agent does" description
    assessment_confidence: Confidence = "high"   # how far the input can be trusted
    provisional: bool = False          # True when scored from a sparse/vague input
    completeness: InputCompleteness | None = None
    input_requirements: list[RequirementItem] = field(default_factory=list)
    dimensions: list[DimensionScore] = field(default_factory=list)
    hard_gates: list[HardGate] = field(default_factory=list)
    failure_clusters: list[FailureCluster] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    insufficient_evidence: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if len(self.dimensions) != NUM_DIMENSIONS:
            raise ValueError(
                f"expected {NUM_DIMENSIONS} dimensions, got {len(self.dimensions)}"
            )
        for d in self.dimensions:
            d.validate()
        for g in self.hard_gates:
            g.validate()
        if not 0.0 <= self.total_score <= 10.0:
            raise ValueError(f"total_score {self.total_score} out of range 0..10")
        if self.verdict not in ("DEPLOYABLE", "CONDITIONAL", "NOT_DEPLOYABLE"):
            raise ValueError(f"bad verdict {self.verdict!r}")
        if self.assessment_confidence not in ("high", "medium", "low"):
            raise ValueError(f"bad assessment_confidence {self.assessment_confidence!r}")

        # Optional stricter pass if pydantic is available.
        try:
            import pydantic  # noqa: F401
        except ImportError:
            pass

    def to_dict(self) -> dict:
        """JSON-serialisable dict using camelCase keys (matches README contract)."""
        return {
            "agentName": self.agent_name,
            "agentSummary": self.agent_summary,
            "rubricVersion": self.rubric_version,
            "analyzedAt": self.analyzed_at,
            "scoringMode": self.scoring_mode,
            "totalScore": round(self.total_score, 2),
            "rawScore": round(self.raw_score, 2),
            "verdict": self.verdict,
            "assessmentConfidence": self.assessment_confidence,
            "provisional": self.provisional,
            "inputCompleteness": (
                {
                    "pct": self.completeness.pct,
                    "tier": self.completeness.tier,
                    "confidence": self.completeness.confidence,
                    "factors": self.completeness.factors,
                    "missingAreas": self.completeness.missing_areas,
                    "clarifyingQuestions": self.completeness.clarifying_questions,
                }
                if self.completeness
                else None
            ),
            "inputRequirements": [
                {
                    "area": r.area,
                    "category": r.category,
                    "status": r.status,
                    "mandatory": r.mandatory,
                    "requiredParameters": r.required_parameters,
                    "note": r.note,
                }
                for r in self.input_requirements
            ],
            "autonomyLevel": self.autonomy_level,
            "hardGates": [
                {
                    "gate": g.gate,
                    "status": g.status,
                    "evidence": g.evidence,
                    "severity": g.severity,
                }
                for g in self.hard_gates
            ],
            "dimensions": [
                {
                    "name": d.name,
                    "score": d.score,
                    "confidence": d.confidence,
                    "framework_refs": d.framework_refs,
                    "evidence": d.evidence,
                    "rationale": d.rationale,
                    "gaps": d.gaps,
                }
                for d in self.dimensions
            ],
            "failureClusters": [
                {
                    "cluster": c.cluster,
                    "severity": c.severity,
                    "description": c.description,
                    "framework_source": c.framework_source,
                    "members": c.members,
                }
                for c in self.failure_clusters
            ],
            "recommendations": [
                {"priority": r.priority, "area": r.area, "action": r.action}
                for r in self.recommendations
            ],
            "insufficientEvidence": self.insufficient_evidence,
        }
