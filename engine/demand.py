"""
demand.py — Builds the Demand String for each transition.

Rules (V20.0):
1. If Target has a detector → IsActive(Det_[Target])
2. For each higher-priority sibling of Target (same waterfall level, lower sibling_priority
   number) that is NOT the From (Current) stage → add IsInactive(Det_[Sibling])
3. Waterfall: if transitioning exactly ONE level UP (from_level → from_level-1 = target_level),
   add IsInactive for every stage one level BELOW the source (from_level + 1).
4. Empty → return '' (never write 'true').

NOTE: Waterfall applies even when target has NO detector.
"""

from __future__ import annotations
from engine.parser import StageProps


def build_demand(target: str,
                 from_stage: str,
                 stage_props: dict[str, StageProps]) -> str:
    """
    Return the demand string for a transition from_stage → target.
    Returns '' if no demand conditions apply.
    """
    target_props = stage_props.get(target)
    from_props   = stage_props.get(from_stage)

    parts: list[str] = []

    # ── 1. IsActive for the target detector ──────────────────────────────────
    if target_props and target_props.detector:
        parts.append(f"IsActive({target_props.detector})")

        # ── 2. IsInactive for higher-priority siblings ────────────────────────
        target_level    = target_props.waterfall_level
        target_priority = target_props.sibling_priority

        if target_level is not None and target_priority is not None:
            siblings = sorted(
                [p for p in stage_props.values()
                 if p.waterfall_level == target_level
                 and p.sibling_priority is not None
                 and p.sibling_priority < target_priority
                 and p.name != from_stage
                 and p.name != target
                 and p.detector],
                key=lambda p: p.sibling_priority
            )
            for sib in siblings:
                parts.append(f"IsInactive({sib.detector})")

    # ── 3. Waterfall (exactly one level up) ───────────────────────────────────
    target_level = target_props.waterfall_level if target_props else None
    from_level   = from_props.waterfall_level   if from_props  else None

    if from_level is not None and target_level is not None:
        if from_level - target_level == 1:
            # going exactly one level up → add IsInactive for level (from_level + 1)
            below_level = from_level + 1
            below_stages = sorted(
                [p for p in stage_props.values()
                 if p.waterfall_level == below_level and p.detector],
                key=lambda p: (p.sibling_priority or 99)
            )
            for bp in below_stages:
                inact = f"IsInactive({bp.detector})"
                if inact not in parts:
                    parts.append(inact)

    return ' and '.join(parts)
