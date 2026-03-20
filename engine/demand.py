"""
demand.py — Builds the Demand String for each transition.

Rules (V20.0):
1. If Target has a detector → IsActive(Det_[Target])
2. For each higher-priority sibling of Target (same waterfall level, lower sibling_priority
   number) that is NOT the From (Current) stage → add IsInactive(Det_[Sibling]).
   THIS RULE APPLIES REGARDLESS OF WHETHER THE TARGET ITSELF HAS A DETECTOR.
   Siblings are enumerated in ascending priority order (priority 1 first, then 2, …)
   so every higher-priority entry is explicitly accounted for as inactive.
   EXCEPTION — Redundancy elimination: if the sibling's IsInactive expression is
   logically always-true given the target's IsActive expression (i.e. any top-level
   OR-disjunct of the sibling's IsInactive matches a top-level AND-conjunct of the
   target's IsActive), the check is skipped as it adds no information.
3. Waterfall: if transitioning exactly ONE level UP (from_level → from_level-1 = target_level),
   add IsInactive for every stage one level BELOW the source (from_level + 1).
4. Empty → return '' (never write 'true').

Detector expressions support Python-style boolean syntax:
  - Single:  'Pc'
  - OR:      'D6 or D10'
  - AND:     'D2 and D5'
  - Complex: '(D2 or Pa) and not Pb'

IsActive transforms the expression directly.
IsInactive applies De Morgan's law recursively (or↔and swapped, not flipped).

Example — B, B1, B2 are siblings (priorities 1, 2, 3) with detectors Pc, Phg, none:
  A → B  : IsActive(Pc)
  A → B1 : IsActive(Phg) and IsInactive(Pc)
  A → B2 : IsInactive(Pc) and IsInactive(Phg)   ← no IsActive (B2 has no detector),
                                                    but sibling checks still required
"""

from __future__ import annotations
import ast as _ast
import re as _re
from engine.parser import StageProps


# ── Boolean expression transformer ────────────────────────────────────────────

def _transform_expr(expr: str, mode: str) -> str:
    """
    Parse a boolean detector expression and transform into JNET function calls.

    mode='active'   → IsActive(X) for atoms; 'not X' → IsInactive(X)
    mode='inactive' → IsInactive(X) for atoms; De Morgan applied (swap and/or, flip not)

    Examples (active):
      'Pc'                     → 'IsActive(Pc)'
      'D6 or D10'              → 'IsActive(D6) or IsActive(D10)'
      '(D2 or Pa) and not Pb'  → '(IsActive(D2) or IsActive(Pa)) and IsInactive(Pb)'

    Examples (inactive / De Morgan):
      'Pc'                     → 'IsInactive(Pc)'
      'D6 or D10'              → 'IsInactive(D6) and IsInactive(D10)'
      '(D2 or Pa) and not Pb'  → '(IsInactive(D2) and IsInactive(Pa)) or IsActive(Pb)'
    """
    # Normalise keyword case: AND/OR/NOT → and/or/not (preserves detector names)
    expr = _re.sub(r'\b(and|or|not)\b', lambda m: m.group(0).lower(), expr.strip(),
                   flags=_re.IGNORECASE)
    try:
        tree = _ast.parse(expr, mode='eval')
    except SyntaxError as e:
        raise ValueError(f"Invalid detector expression '{expr}': {e}") from e
    result = _node_to_jnet(tree.body, mode, parent_is_boolop=False)
    # Always wrap compound expressions in parens so they are safe to join
    # with 'and' in demand strings without operator-precedence ambiguity.
    if isinstance(tree.body, _ast.BoolOp):
        return f"({result})"
    return result


def _node_to_jnet(node, mode: str, parent_is_boolop: bool) -> str:
    """Recursively convert an AST node to a JNET logic string."""
    if isinstance(node, _ast.Name):
        fn = 'IsActive' if mode == 'active' else 'IsInactive'
        return f"{fn}({node.id})"

    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.Not):
        # 'not X' flips the mode
        flipped = 'inactive' if mode == 'active' else 'active'
        return _node_to_jnet(node.operand, flipped, parent_is_boolop=False)

    if isinstance(node, _ast.BoolOp):
        if mode == 'active':
            op_str = ' or ' if isinstance(node.op, _ast.Or) else ' and '
        else:  # De Morgan: swap and ↔ or
            op_str = ' and ' if isinstance(node.op, _ast.Or) else ' or '

        children = [_node_to_jnet(v, mode, parent_is_boolop=True) for v in node.values]
        inner = op_str.join(children)
        # Add parentheses only when nested inside another BoolOp (clarifies precedence)
        return f"({inner})" if parent_is_boolop else inner

    raise ValueError(f"Unsupported AST node in detector expression: {_ast.dump(node)}")


# ── Redundancy helpers ─────────────────────────────────────────────────────────

def _strip_outer_parens(s: str) -> str:
    """Remove one layer of matching outer parentheses if they span the whole string."""
    s = s.strip()
    if not (s.startswith('(') and s.endswith(')')):
        return s
    depth = 0
    for i, c in enumerate(s):
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if depth == 0:
            return s[1:-1] if i == len(s) - 1 else s
    return s


def _split_top_level(expr: str, op: str) -> list[str]:
    """Split expr by 'op' (' and ' or ' or ') at parenthesis depth 0 only."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    i = 0
    while i < len(expr):
        if expr[i] == '(':
            depth += 1
            current.append(expr[i])
            i += 1
        elif expr[i] == ')':
            depth -= 1
            current.append(expr[i])
            i += 1
        elif depth == 0 and expr[i:i + len(op)] == op:
            parts.append(''.join(current).strip())
            current = []
            i += len(op)
        else:
            current.append(expr[i])
            i += 1
    if current:
        parts.append(''.join(current).strip())
    return parts


def _is_redundant_inactive(sibling_inactive: str, target_active: str) -> bool:
    """
    Return True if sibling_inactive is always-true given target_active.

    Detected when any top-level OR-disjunct of sibling_inactive appears verbatim
    as a top-level AND-conjunct of target_active — meaning target_active already
    guarantees one clause of the sibling disjunction, making the whole OR true.

    Example:
      target_active   = '((IsActive(D2) or IsActive(Pa)) and IsInactive(Pb))'
      sibling_inactive= '((IsInactive(D2) and IsInactive(Pa)) or IsInactive(Pb))'
      → 'IsInactive(Pb)' is both a conjunct of target and a disjunct of sibling → True
    """
    t_conjuncts  = set(_split_top_level(_strip_outer_parens(target_active),   ' and '))
    s_disjuncts  = set(_split_top_level(_strip_outer_parens(sibling_inactive), ' or '))
    return bool(t_conjuncts & s_disjuncts)


# ── Main demand builder ────────────────────────────────────────────────────────

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
    target_active = ''
    if target_props and target_props.detector:
        target_active = _transform_expr(target_props.detector, 'active')
        parts.append(target_active)

    # ── 2. IsInactive for higher-priority siblings ────────────────────────────
    # Applied regardless of whether the target itself has a detector.
    # Sorted by ascending sibling_priority so every higher-priority sibling
    # is explicitly checked as inactive (not implied by command ordering).
    # Skipped when the sibling's IsInactive is logically implied by the target's
    # IsActive (redundancy elimination — see _is_redundant_inactive).
    if target_props:
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
                inact = _transform_expr(sib.detector, 'inactive')
                if target_active and _is_redundant_inactive(inact, target_active):
                    continue
                parts.append(inact)

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
                inact = _transform_expr(bp.detector, 'inactive')
                if inact not in parts:
                    parts.append(inact)

    return ' and '.join(parts)
