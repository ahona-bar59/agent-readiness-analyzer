"""Failure Clustering node (Google Automatic-Loss-Analysis style).

Takes the per-dimension gaps and groups them into named, semantic failure
clusters so the report surfaces *systemic* risk rather than a flat list of
nitpicks. A cluster only appears if at least one of its trigger dimensions
scored below the "strong" band and produced gaps.
"""
from __future__ import annotations

from .rubric import CLUSTER_TAXONOMY, DIMENSIONS_BY_KEY
from .schema import DimensionScore, FailureCluster

# Map dimension display name -> key, so we can look up scores by dimension key.
_NAME_TO_KEY = {d.name: d.key for d in DIMENSIONS_BY_KEY.values()}


def detect_clusters(dimensions: list[DimensionScore]) -> list[FailureCluster]:
    by_key = {}
    for ds in dimensions:
        key = _NAME_TO_KEY.get(ds.name)
        if key:
            by_key[key] = ds

    clusters: list[FailureCluster] = []
    for cdef in CLUSTER_TAXONOMY:
        members: list[str] = []
        weak = False
        for dim_key in cdef.trigger_dimensions:
            ds = by_key.get(dim_key)
            if ds is None:
                continue
            if ds.score < 2.0:
                weak = True
                members.extend(ds.gaps)
        if weak and members:
            # De-duplicate while preserving order.
            seen = set()
            unique = [m for m in members if not (m in seen or seen.add(m))]
            clusters.append(
                FailureCluster(
                    cluster=cdef.name,
                    severity=cdef.severity,
                    members=unique,
                    framework_source=cdef.framework_source,
                )
            )
    return clusters
