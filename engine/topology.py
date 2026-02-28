"""
topology.py — Graph operations: path finding, LRT detection, suffix application.
"""

from __future__ import annotations
from engine.config import is_lrt, is_lig, is_vehicle


# ── Graph building ─────────────────────────────────────────────────────────────

def build_graph(transitions) -> dict[str, list[str]]:
    """Return adjacency list {from_stage: [to_stage, ...]}."""
    graph: dict[str, list[str]] = {}
    for t in transitions:
        graph.setdefault(t.from_stage, [])
        if t.to_stage not in graph[t.from_stage]:
            graph[t.from_stage].append(t.to_stage)
    return graph


# ── Suffix application ─────────────────────────────────────────────────────────

def apply_suffix(stage: str, stage_props: dict) -> str:
    """Return stage name with its cpn/min suffix."""
    props = stage_props.get(stage)
    if props:
        return f"{stage}{props.min_type}"
    return f"{stage}min"   # default fallback


def build_wtg_string(stages: list[str], stage_props: dict) -> str:
    """
    Given an ordered list of stage names, apply suffix rules:
    - First element: no suffix
    - Last element: no suffix
    - All middle elements: cpn or min suffix
    Returns underscore-joined string.
    """
    if not stages:
        return ''
    if len(stages) == 1:
        return stages[0]

    result = [stages[0]]
    for s in stages[1:-1]:
        result.append(apply_suffix(s, stage_props))
    result.append(stages[-1])
    return '_'.join(result)


def build_at_string(stages: list[str], jl_final: str, stage_props: dict) -> str:
    """
    Build an AT time string: stages[0]_[middle suffixed]_..._jLXX
    First element bare, middle suffixed, last = jl_final (no suffix).
    """
    if not stages:
        return jl_final
    if len(stages) == 1:
        return f"{stages[0]}_{jl_final}"

    result = [stages[0]]
    for s in stages[1:]:
        result.append(apply_suffix(s, stage_props))
    result.append(jl_final)
    return '_'.join(result)


# ── Rest-of-skeleton parsing ───────────────────────────────────────────────────

def parse_rest_of_skeleton(rest_str: str, stage_props: dict,
                            vehicle_anchor: str, lrt_anchor: str) -> list[str]:
    """
    Parse 'B-C-A0' → ['B', 'C', 'A0']
    'end of skeleton' → []   (means To is already the anchor or end)
    """
    rest = rest_str.strip()
    if not rest or rest.lower() in ('end of skeleton', 'end'):
        return []
    parts = [p.strip() for p in rest.replace('→', '-').split('-')]
    return [p for p in parts if p]


def rest_to_wtg_suffix_string(rest_stages: list[str], stage_props: dict,
                               vehicle_anchor: str, lrt_anchor: str,
                               insert_dq_after_lrt: bool = False) -> str:
    """
    Convert a rest-of-skeleton stage list to a WTG suffix string (no leading stage).
    Middle stages get suffixes; last stage (anchor) does not.
    Optionally inserts DQ after any LRT stage in the list.
    Returns e.g. 'Bcpn_Ccpn_A0' or 'DQ_Bcpn_Ccpn_A0'
    """
    if not rest_stages:
        return ''

    result = []
    for i, s in enumerate(rest_stages):
        is_last = (i == len(rest_stages) - 1)
        if s == 'DQ':
            result.append('DQ')
            continue
        if is_last:
            result.append(s)
        else:
            result.append(apply_suffix(s, stage_props))
        # Insert DQ after an LRT non-anchor stage if requested
        if insert_dq_after_lrt and is_lrt(s) and s != lrt_anchor and not is_last:
            result.append('DQ')

    return '_'.join(result)


# ── LRT reachability ───────────────────────────────────────────────────────────

def find_outgoing_lrts(stage: str, graph: dict[str, list[str]]) -> list[str]:
    """Return list of LRT stages directly reachable from `stage`."""
    return [s for s in graph.get(stage, []) if is_lrt(s)]


def find_nearest_lrt_from_stage(stage: str, graph: dict[str, list[str]],
                                  lrt_anchor: str) -> str | None:
    """
    BFS from `stage` to find the nearest LRT stage (fewest hops).
    Returns the LRT stage name (e.g. 'L39'), or None if unreachable.
    """
    from collections import deque
    visited = {stage}
    queue = deque([(stage, 0)])
    nearest_lrt = None
    nearest_dist = float('inf')

    while queue:
        current, dist = queue.popleft()
        if dist >= nearest_dist:
            continue
        for neighbour in graph.get(current, []):
            if neighbour in visited:
                continue
            visited.add(neighbour)
            if is_lrt(neighbour):
                if dist + 1 < nearest_dist:
                    nearest_dist = dist + 1
                    nearest_lrt = neighbour
            else:
                queue.append((neighbour, dist + 1))

    return nearest_lrt


def lrt_to_j(lrt_stage: str) -> str:
    """'L39' → 'jL39'"""
    return f"j{lrt_stage}"


# ── Validate topology ──────────────────────────────────────────────────────────

def validate_topology(transitions, vehicle_anchor: str) -> None:
    """
    Check that every stage in `To` also appears in `From`
    (excluding the vehicle anchor as a terminal).
    Raises ValueError on dead ends.
    """
    from_stages = {t.from_stage for t in transitions}
    for t in transitions:
        if t.to_stage == vehicle_anchor:
            continue
        if t.to_stage not in from_stages:
            raise ValueError(
                f"Topology dead end: stage '{t.to_stage}' appears as a target "
                f"but has no outgoing transitions. Check the Inter-Stages table."
            )
