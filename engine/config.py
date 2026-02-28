"""
config.py — Stage classification rules and template selector.
Edit this file to change which template is used for a given transition type,
or to adjust what counts as an LRT/Lig/Vehicle stage.
"""

import re

# ── Stage name patterns ────────────────────────────────────────────────────────
LRT_PATTERN = re.compile(r'^L\d+$')        # L30, L31, L39, L10, L20 …
# Lig stages are named A + (same number as their LRT), e.g. A30↔L30, A39↔L39.
# They always have a corresponding LRT stage. The safest pattern: A followed by
# a digit 3–9 and one more digit (covers A30–A39, A40–A49 …).
# This correctly excludes vehicle stages A0, A01, A1, A2 etc.
LIG_PATTERN = re.compile(r'^A[3-9]\d$')   # A30, A31, A39 … NOT A01, A0, A1

# ── Template selector ──────────────────────────────────────────────────────────
# (from_type, to_type) → template letter
TEMPLATE_MAP = {
    ('vehicle', 'vehicle'):      'A',
    ('vehicle', 'lrt_entry'):    'B',
    ('vehicle', 'lrt_anchor'):   'C',
    ('lrt',     'vehicle'):      'D',
    ('lrt',     'lig'):          'E',
    ('lig',     'vehicle'):      'F',
    ('lrt',     'lrt'):          'G',   # LRT entry → LRT entry
    ('lrt',     'lrt_anchor'):   'G',   # LRT entry → LRT anchor (e.g. L30 → L39)
}


def is_lrt(stage: str) -> bool:
    return bool(LRT_PATTERN.match(stage))


def is_lig(stage: str) -> bool:
    return bool(LIG_PATTERN.match(stage))


def is_vehicle(stage: str) -> bool:
    return not is_lrt(stage) and not is_lig(stage)


def classify_stage(stage: str, lrt_anchor: str) -> str:
    """Return one of: 'vehicle', 'lrt_anchor', 'lrt_entry', 'lrt', 'lig'."""
    if is_lrt(stage):
        return 'lrt_anchor' if stage == lrt_anchor else 'lrt_entry'
    if is_lig(stage):
        return 'lig'
    return 'vehicle'


def get_template(from_stage: str, to_stage: str, lrt_anchor: str) -> str:
    from_type = classify_stage(from_stage, lrt_anchor)
    to_type   = classify_stage(to_stage,   lrt_anchor)

    # Normalise lrt_entry / lrt_anchor → 'lrt' for the from-side lookup
    from_key = 'lrt' if from_type in ('lrt_entry', 'lrt_anchor') else from_type
    to_key   = to_type

    key = (from_key, to_key)
    if key not in TEMPLATE_MAP:
        raise ValueError(f"No template for transition ({from_stage}:{from_type}) → ({to_stage}:{to_type})")
    return TEMPLATE_MAP[key]
