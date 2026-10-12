"""v0.3.16/v0.3.17 — verified series-parallel reconstruction for PLCopen LD import.

Design-aid only. This module never talks to a PLC.

Why it exists (Audit H-DEEP, v0.3.15): the hint-less importer in ``plcopen_xml`` walks
the LD connection graph with a breadth-first heuristic. For 3+ OR levels the walk could
silently drop an inner OR, so a rung could energize where the source wiring does not.

Two pieces live here:

1. :func:`reconstruct_elements` rebuilds Cabinet Studio rung elements from the LD
   graph with a dominator-based series-parallel decomposition. It recurses into every
   nested OR at any depth. Shared contacts may be repeated in more than one OR branch
   (power-equivalent); a coil / function block is never duplicated.
2. :func:`verify_elements` is the fail-safe guard. It evaluates the source LD graph and
   the reconstructed elements over every input combination (bit-parallel truth table)
   and compares the power reaching every coil and function block. Any mismatch means
   the import must be refused (``ValueError``) and NOTHING imported.

Truth-table model (sound for node-to-node equivalence):
- contact: out = in AND (tag value, inverted when NC); every tag is a free input.
- coil:    out = in (Cabinet Studio coils pass power, mid-rung coils allowed).
- function block (timer / counter / compare / math / one-shot / JSR …): out = in AND f,
  where f is a FREE input owned by that block (v0.3.17 NEW-1). The same gated model is
  used on BOTH sides (LD graph and Cabinet Studio elements), so a compare inside an OR
  branch after a series contact means the same thing on both sides. It matches the
  Cabinet Studio scan (compare = power AND condition; timer / counter / math / JSR pass
  power, i.e. f = 1; ONS = power AND not-previous) and IEC ENO / TON.Q (never true
  without EN). If the power INTO every block matches for all values of all free inputs,
  the rungs behave the same whatever each block does internally.
- OSR / OSF one-shots: rung power passes through in Cabinet Studio; in LD the Q pin
  drives only the one-shot output coil (absorbed into the block).
- v0.3.17 NEW-3: every coil / block is also compared by its settings (coil form,
  compare op + operands, timer type + PT, counter type + preset, math op + operands /
  CPT expression, one-shot type / storage / output, JSR target), not only by power.
- v0.3.17 NEW-2: up to EXHAUSTIVE_MAX_INPUTS free inputs the check is an exhaustive
  bit-parallel truth table; above that an exact reduced ordered BDD is used. Nothing is
  ever sampled. Rungs beyond the BDD limits are REFUSED with a clear message.
"""

from __future__ import annotations

from typing import Any

EXHAUSTIVE_MAX_INPUTS = 20
# v0.3.17 NEW-2: exact BDD equivalence above the truth-table size; refuse beyond these.
BDD_MAX_INPUTS = 400
BDD_MAX_NODES = 1_500_000
MAX_RECONSTRUCT_ELEMENTS = 4000

REFUSE_PREFIX = "PLCopen import refused"


class GraphImportError(ValueError):
    """Raised when LD wiring cannot be imported exactly (fail safe, nothing imported)."""


class VerifyLimitError(GraphImportError):
    """v0.3.17 NEW-2: the rung is too large to verify exactly — refuse, never sample."""


# ---------------------------------------------------------------------------
# Graph container
# ---------------------------------------------------------------------------


class LDGraph:
    """One rung of LD wiring: nodes keyed by localId plus ordered pred / succ lists.

    node kinds: ``left``, ``right``, ``contact``, ``coil``, ``fb``.
    ``el`` holds the Cabinet Studio element built from the node (contact / coil / fb).
    ``passthrough`` marks OSR / OSF blocks; ``absorbed`` marks their output coil.
    """

    def __init__(self, left_id: str) -> None:
        self.left = left_id
        self.nodes: dict[str, dict[str, Any]] = {left_id: {"kind": "left"}}
        self.preds: dict[str, list[str]] = {left_id: []}

    def add_node(self, nid: str, kind: str, el: dict[str, Any] | None = None, **extra: Any) -> None:
        self.nodes[nid] = {"kind": kind, "el": el, **extra}
        self.preds.setdefault(nid, [])

    def add_edge(self, src: str, dst: str) -> None:
        lst = self.preds.setdefault(dst, [])
        if src not in lst:
            lst.append(src)

    # derived ---------------------------------------------------------------
    def succs(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {n: [] for n in self.nodes}
        for dst, ps in self.preds.items():
            for p in ps:
                if p in out and dst in self.nodes:
                    out[p].append(dst)
        return out


def _order_key(nid: str) -> tuple[int, str]:
    try:
        return (int(nid), nid)
    except (TypeError, ValueError):
        return (10**9, str(nid))


def _topo(g: LDGraph, nodes: set[str]) -> list[str]:
    succ = g.succs()
    indeg = {n: 0 for n in nodes}
    for n in nodes:
        for p in g.preds.get(n, []):
            if p in nodes:
                indeg[n] += 1
    ready = sorted([n for n, d in indeg.items() if d == 0], key=_order_key)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for s in succ.get(n, []):
            if s not in nodes:
                continue
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
                ready.sort(key=_order_key)
    if len(order) != len(nodes):
        raise GraphImportError(
            f"{REFUSE_PREFIX}: the rung wiring has a feedback loop (cycle), which Cabinet Studio "
            "cannot represent. Nothing was imported."
        )
    return order


def reachable_nodes(g: LDGraph) -> set[str]:
    succ = g.succs()
    seen: set[str] = set()
    stack = [g.left]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(succ.get(n, []))
    return seen


def _is_effect(g: LDGraph, nid: str) -> bool:
    node = g.nodes.get(nid) or {}
    return node.get("kind") in {"coil", "fb"} and not node.get("absorbed")


def effect_nodes(g: LDGraph, live: set[str]) -> list[str]:
    return sorted([n for n in live if _is_effect(g, n)], key=_order_key)


def live_nodes(g: LDGraph) -> set[str]:
    """Nodes reachable from the left rail that can still reach a coil / block / right rail.

    Dead-end contact chains carry no logic and are ignored on both sides.
    """
    reach = reachable_nodes(g)
    succ = g.succs()
    useful: set[str] = set()
    order = _topo(g, reach)
    for n in reversed(order):
        node = g.nodes.get(n) or {}
        if node.get("kind") in {"coil", "fb", "right"}:
            useful.add(n)
            continue
        if any(s in useful for s in succ.get(n, []) if s in reach):
            useful.add(n)
    useful.add(g.left)
    return useful


# ---------------------------------------------------------------------------
# Bit-parallel truth tables
# ---------------------------------------------------------------------------


class _Table:
    """Exhaustive bit-parallel truth table (one bit per input combination)."""

    method = "exact"

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        k = len(self.names)
        if k > EXHAUSTIVE_MAX_INPUTS:  # pragma: no cover - callers pick _BDD instead
            raise VerifyLimitError(f"{REFUSE_PREFIX}: internal truth-table limit exceeded.")
        rows = 1 << k
        self.rows = rows
        self.all = (1 << rows) - 1
        self.true = self.all
        self.false = 0
        self.cols: dict[str, int] = {}
        for i, name in enumerate(self.names):
            half = 1 << i
            period = half << 1
            unit = ((1 << half) - 1) << half
            rep = self.all // ((1 << period) - 1) if period <= rows else 0
            self.cols[name] = (unit * rep) & self.all if period <= rows else 0

    def var(self, name: str) -> int:
        return self.cols.get(name, 0)

    col = var  # back-compat

    def and_(self, a: int, b: int) -> int:
        return a & b

    def or_(self, a: int, b: int) -> int:
        return a | b

    def not_(self, a: int) -> int:
        return (~a) & self.all

    def witness(self, x: int) -> dict[str, bool]:
        row = (x & -x).bit_length() - 1
        return {nm: bool((self.cols[nm] >> row) & 1) for nm in self.names}


class _BDD:
    """v0.3.17 NEW-2: exact reduced ordered BDD (hash-consed; equal functions ⇔ equal ids).

    Used above EXHAUSTIVE_MAX_INPUTS instead of the old 65,536-row random sample.
    Node 0 = FALSE, node 1 = TRUE. Exceeding BDD_MAX_NODES refuses the import.
    """

    method = "exact-bdd"

    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        if len(self.names) > BDD_MAX_INPUTS:
            raise VerifyLimitError(
                f"{REFUSE_PREFIX}: the rung has {len(self.names)} independent inputs; Cabinet "
                f"Studio verifies at most {BDD_MAX_INPUTS} exactly and will not guess. "
                "Split the rung and import again."
            )
        self.level = {n: i for i, n in enumerate(self.names)}
        big = len(self.names) + 1
        self.nodes: list[tuple[int, int, int]] = [(big, 0, 0), (big, 1, 1)]
        self.unique: dict[tuple[int, int, int], int] = {}
        self.memo: dict[tuple[str, int, int], int] = {}
        self.true = 1
        self.false = 0

    def _mk(self, v: int, lo: int, hi: int) -> int:
        if lo == hi:
            return lo
        key = (v, lo, hi)
        n = self.unique.get(key)
        if n is None:
            if len(self.nodes) >= BDD_MAX_NODES:
                raise VerifyLimitError(
                    f"{REFUSE_PREFIX}: the rung logic is too large to verify exactly "
                    f"(more than {BDD_MAX_NODES:,} decision nodes); Cabinet Studio will not "
                    "guess. Split the rung and import again."
                )
            n = len(self.nodes)
            self.nodes.append(key)
            self.unique[key] = n
        return n

    def var(self, name: str) -> int:
        return self._mk(self.level[name], 0, 1)

    col = var

    def _apply(self, op: str, a: int, b: int) -> int:
        if op == "and":
            if a == 0 or b == 0:
                return 0
            if a == 1:
                return b
            if b == 1 or a == b:
                return a
        else:
            if a == 1 or b == 1:
                return 1
            if a == 0:
                return b
            if b == 0 or a == b:
                return a
        if a > b:
            a, b = b, a
        key = (op, a, b)
        hit = self.memo.get(key)
        if hit is not None:
            return hit
        va, la, ha = self.nodes[a]
        vb, lb, hb = self.nodes[b]
        v = min(va, vb)
        a0, a1 = (la, ha) if va == v else (a, a)
        b0, b1 = (lb, hb) if vb == v else (b, b)
        r = self._mk(v, self._apply(op, a0, b0), self._apply(op, a1, b1))
        self.memo[key] = r
        return r

    def and_(self, a: int, b: int) -> int:
        return self._apply("and", a, b)

    def or_(self, a: int, b: int) -> int:
        return self._apply("or", a, b)

    def not_(self, a: int) -> int:
        if a in (0, 1):
            return 1 - a
        key = ("not", a, a)
        hit = self.memo.get(key)
        if hit is not None:
            return hit
        v, lo, hi = self.nodes[a]
        r = self._mk(v, self.not_(lo), self.not_(hi))
        self.memo[key] = r
        return r

    def witness(self, x: int) -> dict[str, bool]:
        vec = {nm: False for nm in self.names}
        while x > 1:
            v, lo, hi = self.nodes[x]
            if lo != 0:
                x = lo
            else:
                vec[self.names[v]] = True
                x = hi
        return vec


def _algebra(names: list[str]) -> Any:
    if len(names) <= EXHAUSTIVE_MAX_INPUTS:
        return _Table(sorted(names))
    return _BDD(list(names))


def _contact_var(el: dict[str, Any]) -> tuple[str, bool]:
    var = str(el.get("var") or "").strip()
    nc = str(el.get("form") or "NO").upper() == "NC"
    return var, nc


def _collect_contact_vars(elements: list[dict[str, Any]], out: set[str]) -> None:
    for el in elements or []:
        k = str(el.get("kind") or "").lower()
        if k == "contact":
            out.add("v:" + _contact_var(el)[0])
        elif k == "or":
            for b in el.get("branches") or []:
                _collect_contact_vars(list(b or []), out)


def _graph_powers(g: LDGraph, live: set[str], tab: Any) -> dict[str, Any]:
    """Power INTO each effect node (coil / block) of the LD graph."""
    order = _topo(g, live)
    out: dict[str, Any] = {}
    pin: dict[str, Any] = {}
    for n in order:
        node = g.nodes[n]
        kind = node.get("kind")
        if kind == "left":
            out[n] = tab.true
            continue
        p = tab.false
        for pr in g.preds.get(n, []):
            if pr in out:
                p = tab.or_(p, out[pr])
        pin[n] = p
        if kind == "contact":
            var, nc = _contact_var(node.get("el") or {})
            c = tab.var("v:" + var)
            out[n] = tab.and_(p, tab.not_(c) if nc else c)
        elif kind == "coil":
            out[n] = p
        elif kind == "fb":
            # v0.3.17 NEW-1: block output is gated by its input power (ENO / Q ≤ EN).
            out[n] = tab.and_(p, tab.var("f:" + n))
        else:  # right rail
            out[n] = p
    return {n: pin.get(n, tab.false) for n in live if _is_effect(g, n)}


def _element_powers(
    elements: list[dict[str, Any]], tab: Any
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Power INTO each tagged (``_nid``) coil / block of an element list.

    Returns (powers, duplicated_nids, untagged_effects).
    """
    powers: dict[str, Any] = {}
    dups: list[str] = []
    untagged: list[str] = []

    def series(items: list[dict[str, Any]], p: Any) -> Any:
        for el in items or []:
            k = str(el.get("kind") or "").lower()
            if k == "contact":
                var, nc = _contact_var(el)
                c = tab.var("v:" + var)
                p = tab.and_(p, tab.not_(c) if nc else c)
            elif k == "or":
                acc = tab.false
                branches = list(el.get("branches") or [])
                if not branches:
                    continue
                for b in branches:
                    acc = tab.or_(acc, series(list(b or []), p))
                p = tab.and_(acc, p)
            else:
                nid = el.get("_nid")
                if nid is None:
                    untagged.append(k)
                    continue
                nid = str(nid)
                if nid in powers:
                    dups.append(nid)
                powers[nid] = p
                if k == "coil":
                    pass  # passes power
                elif k == "oneshot" and str(el.get("block") or "").upper() in {"OSR", "OSF"}:
                    pass  # rung power passes through
                else:
                    # v0.3.17 NEW-1: same gated block model as the LD graph side.
                    p = tab.and_(p, tab.var("f:" + nid))
        return p

    series(list(elements or []), tab.true)
    return powers, dups, untagged


def _s(v: Any) -> str:
    return str(v if v is not None else "").strip()


def effect_descriptor(el: dict[str, Any]) -> tuple[Any, ...]:
    """v0.3.17 NEW-3: settings of a coil / block that change behaviour (compared node-to-node)."""
    from cabinet_studio.services.ladder_ir import (
        clamp_counter,
        normalize_compare_op,
        normalize_counter_block,
        normalize_math_op,
        normalize_oneshot_block,
    )

    k = str(el.get("kind") or "").lower()
    if k == "coil":
        form = _s(el.get("form") or "normal").lower()
        if form in {"negated", "not", "nc"}:
            form = "negated"
        elif form in {"set", "s", "latch", "otl"}:
            form = "set"
        elif form in {"reset", "r", "unlatch", "otu"}:
            form = "reset"
        else:
            form = "normal"
        return ("coil", _s(el.get("var")), form)
    if k == "timer":
        blk = _s(el.get("block") or "TON").upper()
        if blk not in {"TON", "TOF", "RTO"}:
            blk = "TON"
        try:
            pt = max(0, int(el.get("pt_ms") or 0))
        except (TypeError, ValueError):
            pt = 0
        # v0.3.18 NEW-9: a tag preset is a different setting from any literal.
        if _s(el.get("pt_tag")):
            return ("timer", _s(el.get("var")), blk, "PT=" + _s(el.get("pt_tag")))
        return ("timer", _s(el.get("var")), blk, pt)
    if k == "counter":
        blk_c = normalize_counter_block(el.get("block"))
        if _s(el.get("pv_tag")) and blk_c in {"CTU", "CTD", "LOAD"}:
            return ("counter", _s(el.get("var")), blk_c, "PV=" + _s(el.get("pv_tag")))
        return ("counter", _s(el.get("var")), blk_c, clamp_counter(el.get("pv", 0)))
    if k == "compare":
        op = normalize_compare_op(el.get("op"))
        c = _s(el.get("source_c"))
        return ("compare", op, _s(el.get("source_a")), _s(el.get("source_b")), c if (c or op in {"LIM", "MEQ"}) else "")
    if k == "math":
        op = normalize_math_op(el.get("op"))
        if op == "CPT":
            return ("math", op, _s(el.get("dest")), _s(el.get("expression") or el.get("source_a")))
        if op in {"MOV", "NOT"}:
            return ("math", op, _s(el.get("dest")), _s(el.get("source_a")))
        return ("math", op, _s(el.get("dest")), _s(el.get("source_a")), _s(el.get("source_b")))
    if k == "oneshot":
        return ("oneshot", normalize_oneshot_block(el.get("block")), _s(el.get("var")), _s(el.get("output")))
    if k == "jsr":
        return ("jsr", _s(el.get("target")))
    if k == "sbr":
        return ("sbr", _s(el.get("name")))
    return (k,)


def _describe(d: tuple[Any, ...]) -> str:
    return " ".join(str(x) for x in d if str(x) != "")


def _ordered_names(g: LDGraph, live: set[str], elements: list[dict[str, Any]]) -> list[str]:
    """Input names in first-use (topological) order — a good BDD variable order."""
    names: list[str] = []
    seen: set[str] = set()

    def add(nm: str) -> None:
        if nm not in seen:
            seen.add(nm)
            names.append(nm)

    # v0.3.18 (Audit P3-B): depth-first pre-order from the left rail, so each branch's
    # inputs stay together whatever the file's localId numbering (column-wise ids gave an
    # exponential BDD and false "too large" refusals). Ties break on structure, then id.
    _topo(g, live)  # still refuses feedback loops
    succ = g.succs()

    def skey(n: str) -> tuple[Any, ...]:
        nd = g.nodes.get(n) or {}
        el = nd.get("el") or {}
        return (str(nd.get("kind") or ""), str(el.get("var") or el.get("op") or ""), _order_key(n))

    seen_n: set[str] = set()
    stack = [g.left]
    while stack:
        n = stack.pop()
        if n in seen_n:
            continue
        seen_n.add(n)
        node = g.nodes.get(n) or {}
        if n in live:
            if node.get("kind") == "contact":
                add("v:" + _contact_var(node.get("el") or {})[0])
            elif node.get("kind") == "fb":
                add("f:" + n)
        nxt = sorted((m for m in succ.get(n, []) if m in live and m not in seen_n), key=skey)
        stack.extend(reversed(nxt))
    for n in sorted(live, key=_order_key):  # anything not reached (defensive)
        node = g.nodes.get(n) or {}
        if node.get("kind") == "contact":
            add("v:" + _contact_var(node.get("el") or {})[0])
        elif node.get("kind") == "fb":
            add("f:" + n)
    extra: set[str] = set()
    _collect_contact_vars(elements, extra)
    for nm in sorted(extra):
        add(nm)
    return names


def verify_elements(g: LDGraph, elements: list[dict[str, Any]]) -> tuple[bool, str]:
    """Exact check: elements vs source LD graph, node-to-node (power AND settings).

    Returns (True, "exact" | "exact-bdd") or (False, reason). Raises VerifyLimitError
    (a GraphImportError) when the rung is too large to verify exactly — never samples.
    """
    try:
        return _verify_elements(g, elements)
    except RecursionError:
        raise VerifyLimitError(
            f"{REFUSE_PREFIX}: the rung is nested too deeply to verify. Simplify it and import again."
        ) from None


def _verify_elements(g: LDGraph, elements: list[dict[str, Any]]) -> tuple[bool, str]:
    live = live_nodes(g)
    effects = effect_nodes(g, live)
    tab = _algebra(_ordered_names(g, live, elements))
    gp = _graph_powers(g, live, tab)
    ep, dups, untagged = _element_powers(elements, tab)
    if dups:
        return False, f"coil/block duplicated in reconstruction (localId {sorted(set(dups))})"
    if untagged:
        return False, f"element(s) {untagged} not traceable to the source wiring"
    missing = [n for n in effects if n not in ep]
    if missing:
        return False, f"coil/block localId {missing} missing from reconstruction"
    extra = [n for n in ep if n not in gp]
    if extra:
        return False, f"element localId {extra} not wired in the source rung"
    # v0.3.17 NEW-3: settings (coil form / block parameters) must match the wiring too.
    tagged: dict[str, dict[str, Any]] = {}

    def collect(items: list[dict[str, Any]]) -> None:
        for el in items or []:
            if str(el.get("kind") or "").lower() == "or":
                for b in el.get("branches") or []:
                    collect(list(b or []))
            elif el.get("_nid") is not None:
                tagged[str(el["_nid"])] = el

    collect(list(elements or []))
    for n in effects:
        src = g.nodes[n].get("el") or {}
        mine = tagged.get(n) or {}
        d_src, d_mine = effect_descriptor(src), effect_descriptor(mine)
        if d_src != d_mine:
            return False, (
                f"settings of {_describe(d_src)} (localId {n}) differ from the wiring: "
                f"element says [{_describe(d_mine)}], wiring says [{_describe(d_src)}]"
            )
    for n in effects:
        if gp[n] != ep[n]:
            diff = tab.or_(tab.and_(gp[n], tab.not_(ep[n])), tab.and_(ep[n], tab.not_(gp[n])))
            unsafe_set = tab.and_(ep[n], tab.not_(gp[n]))
            unsafe = unsafe_set != tab.false
            vec = tab.witness(unsafe_set if unsafe else diff)
            on = ", ".join(sorted(k[2:] for k, v in vec.items() if v and k.startswith("v:"))) or "none"
            blocks = ", ".join(sorted(k[2:] for k, v in vec.items() if v and k.startswith("f:")))
            if blocks:
                on += f"; block outputs TRUE at localId {blocks}"
            what = "would ENERGIZE where the source wiring does not" if unsafe else "differs from the source wiring"
            el = (g.nodes[n].get("el") or {})
            label = el.get("var") or el.get("kind") or n
            return False, (
                f"power into {label} (localId {n}) {what}; first differing input set: TRUE = {on}"
            )
    return True, tab.method


# ---------------------------------------------------------------------------
# Series-parallel reconstruction
# ---------------------------------------------------------------------------


def _strip_for_reconstruct(g: LDGraph, live: set[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Working preds map: absorbed one-shot output coils removed, OSR/OSF made inline.

    Returns (preds, sink_targets).
    """
    preds = {n: [p for p in g.preds.get(n, []) if p in live] for n in live}
    for n in sorted(live, key=_order_key):
        if g.nodes[n].get("absorbed"):
            preds.pop(n, None)
    for n in list(preds):
        preds[n] = [p for p in preds[n] if p in preds]
    # OSR / OSF pass rung power through: insert the block after its predecessors.
    for b in sorted([n for n in preds if g.nodes[n].get("passthrough")], key=_order_key):
        pset = set(preds[b])
        if not pset:
            continue
        for s in list(preds):
            if s == b:
                continue
            sp = preds[s]
            if pset <= set(sp):
                newp = [p for p in sp if p not in pset]
                newp.append(b)
                preds[s] = newp
    succ: dict[str, list[str]] = {n: [] for n in preds}
    for d, ps in preds.items():
        for p in ps:
            succ.setdefault(p, []).append(d)
    targets: list[str] = []
    for n in preds:
        kind = g.nodes[n].get("kind")
        if kind == "right":
            for p in preds[n]:
                if p not in targets:
                    targets.append(p)
    for n in preds:
        kind = g.nodes[n].get("kind")
        if kind in {"coil", "fb"} and not succ.get(n) and n not in targets:
            targets.append(n)
    for n in [n for n in preds if g.nodes[n].get("kind") == "right"]:
        preds.pop(n, None)
    targets = [t for t in targets if t in preds]
    return preds, targets


def _node_label(g: LDGraph, nid: str) -> str:
    node = g.nodes.get(nid) or {}
    el = node.get("el") or {}
    name = el.get("var") or el.get("op") or el.get("block") or node.get("kind") or "?"
    return f"{name} (localId {nid})"


def bridged_fan_in(g: LDGraph) -> str | None:
    """v0.3.20 (fuzz seeds 298336 / 298395): in a series / OR rung every instruction fed
    by the same node is fed by exactly the same set of wires (one join per split point).
    A partial cross-wiring - typically one wire of an OR-into-OR join deleted - can only
    be drawn by repeating contacts, so it is refused instead of rebuilt."""
    live = live_nodes(g)
    preds, _targets = _strip_for_reconstruct(g, live)
    succ: dict[str, list[str]] = {}
    for d, ps in preds.items():
        for p in ps:
            succ.setdefault(p, []).append(d)
    for n in sorted(succ, key=_order_key):
        fed = sorted(set(succ[n]), key=_order_key)
        sets = {s: frozenset(preds[s]) for s in fed}
        if len(set(sets.values())) <= 1:
            continue
        a, b = fed[0], next(s for s in fed if sets[s] != sets[fed[0]])

        def names(ids: frozenset[str]) -> str:
            return ", ".join(_node_label(g, x) for x in sorted(ids, key=_order_key))

        return (
            f"the wiring is cross-connected: {_node_label(g, a)} is fed by {names(sets[a])} but "
            f"{_node_label(g, b)} is fed by {names(sets[b])}. That cannot be drawn as series / OR "
            "branches without repeating contacts, and it is what a deleted or extra wire looks "
            "like. Nothing was imported"
        )
    return None


def reconstruct_elements(g: LDGraph) -> list[dict[str, Any]]:
    """Rebuild rung elements from LD wiring (any OR depth). Elements carry ``_nid``."""
    live = live_nodes(g)
    preds, targets = _strip_for_reconstruct(g, live)
    # Virtual join nodes: every distinct fan-in set (≥2 wires into one point) becomes a
    # single invisible node, so an OR that feeds several next instructions is factored
    # once instead of being copied into each (keeps the rebuild linear, not 2^n).
    joins: dict[frozenset[str], str] = {}
    virtual: set[str] = set()
    for n in sorted(list(preds), key=_order_key):
        ps = preds[n]
        if len(set(ps)) < 2:
            continue
        key = frozenset(ps)
        j = joins.get(key)
        if j is None:
            j = f"~join{len(joins) + 1}"
            joins[key] = j
            virtual.add(j)
            preds[j] = sorted(key, key=_order_key)
        preds[n] = [j]
    if len(set(targets)) >= 2 and frozenset(targets) in joins:
        targets = [joins[frozenset(targets)]]
    nodes = set(preds)
    if not targets or targets == [g.left]:
        return []
    # topo + dominators + ancestors
    succ: dict[str, list[str]] = {n: [] for n in nodes}
    for d, ps in preds.items():
        for p in ps:
            succ[p].append(d)
    indeg = {n: len(preds[n]) for n in nodes}
    ready = sorted([n for n in nodes if indeg[n] == 0], key=_order_key)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for s in sorted(succ[n], key=_order_key):
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
        ready.sort(key=_order_key)
    if len(order) != len(nodes):
        raise GraphImportError(f"{REFUSE_PREFIX}: rung wiring has a cycle. Nothing was imported.")
    dom: dict[str, frozenset[str]] = {}
    anc: dict[str, frozenset[str]] = {}
    for n in order:
        ps = preds[n]
        if not ps:
            dom[n] = frozenset({n})
            anc[n] = frozenset({n})
            continue
        common = None
        a: set[str] = {n}
        for p in ps:
            common = set(dom[p]) if common is None else (common & dom[p])
            a |= anc[p]
        dom[n] = frozenset((common or set()) | {n})
        anc[n] = frozenset(a)
    desc: dict[str, set[str]] = {n: {n} for n in nodes}
    for n in reversed(order):
        for s in succ[n]:
            desc[n] |= desc[s]

    budget = [0]

    def el_of(n: str) -> dict[str, Any] | None:
        if n in virtual:
            return None
        node = g.nodes[n]
        el = dict(node.get("el") or {})
        el["_nid"] = n
        budget[0] += 1
        if budget[0] > MAX_RECONSTRUCT_ELEMENTS:
            raise GraphImportError(
                f"{REFUSE_PREFIX}: rung wiring is too tangled to rebuild as series / OR "
                "branches. Nothing was imported."
            )
        return el

    def deepest_common_dom(ts: set[str]) -> str:
        common: set[str] | None = None
        for t in ts:
            common = set(dom[t]) if common is None else (common & dom[t])
        if not common:
            raise GraphImportError(f"{REFUSE_PREFIX}: rung has more than one power source. Nothing was imported.")
        return max(common, key=lambda x: len(dom[x]))

    def expr(src: str, ts: set[str]) -> list[dict[str, Any]]:
        # v0.3.17 NEW-7: iterative along series chains (no RecursionError on long
        # rungs); recursion depth is bounded by OR nesting depth only.
        ts = set(ts)
        chunks_rev: list[list[dict[str, Any]]] = []
        while True:
            if ts == {src}:
                break
            if src in ts:
                raise GraphImportError(
                    f"{REFUSE_PREFIX}: an OR branch has no instruction in it (a shorting wire). "
                    "Nothing was imported."
                )
            if len(ts) == 1:
                (t,) = tuple(ts)
                e = el_of(t)
                if e is not None:
                    chunks_rev.append([e])
                ts = set(preds[t])
                continue
            d = deepest_common_dom(ts)
            if d in ts:
                raise GraphImportError(
                    f"{REFUSE_PREFIX}: an OR branch bypasses part of another branch (shorting "
                    "wire). Nothing was imported."
                )
            chunks_rev.append(or_block(d, ts))
            ts = {d}
        out: list[dict[str, Any]] = []
        for chunk in reversed(chunks_rev):
            out.extend(chunk)
        return out

    def or_block(d: str, ts: set[str]) -> list[dict[str, Any]]:
        tl = sorted(ts, key=_order_key)
        region = {t: (set(anc[t]) & desc[d]) - {d} for t in tl}
        parent = {t: t for t in tl}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, a in enumerate(tl):
            for b in tl[i + 1:]:
                if region[a] & region[b]:
                    parent[find(a)] = find(b)
        groups: dict[str, list[str]] = {}
        for t in tl:
            groups.setdefault(find(t), []).append(t)
        ordered = sorted(groups.values(), key=lambda grp: min(_order_key(x) for x in grp))
        branches: list[list[dict[str, Any]]] = []
        for grp in ordered:
            gs = set(grp)
            if len(gs) == 1:
                branches.append(expr(d, gs))
                continue
            d2 = deepest_common_dom(gs)
            if d2 == d:
                # Shared nodes but no single split point (typical: an OR feeding the
                # next OR, so every target has the SAME predecessor set). Factor by
                # predecessor set: OR(out t) = (OR of preds) · (t1 | t2 …). Different
                # predecessor sets become separate branches (contacts may repeat —
                # power-equivalent; a coil / block never repeats — verify checks).
                by_preds: dict[frozenset[str], list[str]] = {}
                for t in sorted(gs, key=_order_key):
                    by_preds.setdefault(frozenset(preds[t]), []).append(t)
                for pset, members in sorted(
                    by_preds.items(), key=lambda kv: min(_order_key(x) for x in kv[1])
                ):
                    head = expr(d, set(pset))
                    tails = [[e] for e in (el_of(t) for t in members) if e is not None]
                    if len(tails) != len(members):
                        raise GraphImportError(
                            f"{REFUSE_PREFIX}: rung wiring could not be factored into series / OR "
                            "branches. Nothing was imported."
                        )
                    if len(tails) == 1:
                        branches.append(head + tails[0])
                    else:
                        branches.append(head + [{"kind": "or", "branches": tails}])
            else:
                branches.append(expr(d, gs))
        if any(not b for b in branches):
            raise GraphImportError(
                f"{REFUSE_PREFIX}: an OR branch has no instruction in it. Nothing was imported."
            )
        if len(branches) == 1:
            return branches[0]
        return [{"kind": "or", "branches": branches}]

    try:
        return expr(g.left, set(targets))
    except RecursionError:
        raise GraphImportError(
            f"{REFUSE_PREFIX}: the rung is nested too deeply to rebuild. Nothing was imported."
        ) from None


def strip_nids(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for el in elements or []:
        e = {k: v for k, v in el.items() if k != "_nid"}
        if str(e.get("kind") or "").lower() == "or":
            e["branches"] = [strip_nids(list(b or [])) for b in e.get("branches") or []]
        out.append(e)
    return out


def tag_effects_in_order(g: LDGraph, elements: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """For a Cabinet Studio hint: map coil / block elements to LD nodes by emission order.

    The exporter writes coils / blocks in depth-first element order, so the k-th effect
    element is the k-th effect node (by localId). Returns tagged deep copies, or None
    when counts / kinds / tags disagree (stale or foreign hint).
    """
    live = live_nodes(g)
    effects = effect_nodes(g, live)
    flat: list[dict[str, Any]] = []

    def copy(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        res = []
        for el in items or []:
            e = dict(el)
            k = str(e.get("kind") or "").lower()
            if k == "or":
                e["branches"] = [copy(list(b or [])) for b in e.get("branches") or []]
            elif k != "contact":
                flat.append(e)
            res.append(e)
        return res

    tagged = copy(list(elements or []))
    if len(flat) != len(effects):
        return None
    for e, n in zip(flat, effects):
        node = g.nodes[n]
        k = str(e.get("kind") or "").lower()
        if node.get("kind") == "coil":
            if k != "coil" or str(e.get("var") or "") != str((node.get("el") or {}).get("var") or ""):
                return None
        elif k == "coil":
            return None
        e["_nid"] = n
    return tagged
