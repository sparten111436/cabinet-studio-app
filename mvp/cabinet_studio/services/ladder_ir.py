"""Cabinet Studio Educational Ladder IR (v3 / v0.3.8).

First-party intermediate representation for NO/NC contacts, coils,
TON/TOF/RTO timers, CTU/CTD counters (+ RES / LOAD), series/parallel,
**nested OR branches**, and **mid-rung coils**. Converts to/from the
project.program rung dicts used by the Programming viewer so existing
cabinets keep working.

Nested OR (v0.3.4): an ``or`` element's branches may contain contacts and
further ``or`` groups (educational CCW-style parallel nesting).

Mid-rung coils (v0.3.4): coil elements may appear before the end of a rung;
scan power continues past a coil (OTE-style / CCW educational passthrough)
so later contacts and coils still evaluate.

One-shots (v0.3.6): ``oneshot`` elements — ONS (input-style, passes power for
one scan on a rising rung edge), OSR / OSF (output-style, pulse an output bit
for one scan on a rising / falling rung edge). Rockwell/CCW-style educational
naming; IEC peers are R_TRIG / F_TRIG.

Rich comments (v0.3.6): rung ``comment`` may be multi-line; any element may
carry an instruction note ``desc`` (kept losslessly via ``elements``).

Tag descriptions (v0.3.7): IR variables may carry ``description`` (user text from
``program["tag_descriptions"]`` or the cabinet device description).

Subroutines (v0.3.8): ``jsr`` / ``ret`` / ``sbr`` elements (educational CCW / Studio
style). Main lives in ``rungs``; additional named routines in ``program["routines"]``
and IR ``routines``. Tag aliases (v0.3.8): ``program["tag_aliases"]`` maps a friendly
name onto a base device/program tag.

Not a vendor PLC format. Not MicroLogix / .RSS / Do-more / CODESYS native.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


IR_FORMAT = "cabinet-studio-ladder"
IR_VERSION = 1
IR_DIALECT = "educational-iec"


TIMER_BLOCKS = ("TON", "TOF", "RTO")
# Counter instructions (v0.3.3). CTU/CTD own the counter instance; RES/LOAD act on it.
COUNTER_BLOCKS = ("CTU", "CTD", "RES", "LOAD")
COUNTER_OWNER_BLOCKS = ("CTU", "CTD")
COUNTER_MIN = -32768
COUNTER_MAX = 32767
# Compare / math (v0.3.5) — Micro800/CCW-style educational mnemonics.
COMPARE_OPS = ("EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ", "LIM", "MEQ")
COMPARE_THREE_OPS = ("LIM", "MEQ")  # need source_c (Low/High or Mask/Compare)
MATH_OPS = ("ADD", "SUB", "MUL", "DIV", "MOV", "CPT", "AND", "OR", "XOR", "NOT")
BITWISE_OPS = ("AND", "OR", "XOR", "NOT")
NUMERIC_MIN = -2147483648
NUMERIC_MAX = 2147483647
# Member suffixes readable as contacts, e.g. C1.DN / T1.TT (Rockwell-style names).
MEMBER_SUFFIXES = ("DN", "TT", "EN", "CU", "CD", "OV", "UN", "Q", "ACC", "PRE")
# One-shots (v0.3.6) — Studio/CCW educational mnemonics (IEC: R_TRIG / F_TRIG).
ONESHOT_BLOCKS = ("ONS", "OSR", "OSF")
ONESHOT_OUTPUT_BLOCKS = ("OSR", "OSF")
# Subroutines (v0.3.8) — educational JSR / SBR / RET (CCW / Studio ideas).
SUBROUTINE_KINDS = ("jsr", "sbr", "ret")
JSR_MAX_DEPTH = 8
ROUTINE_NAME_MAX = 48
NOTE_MAX = 240


def normalize_oneshot_block(block: object) -> str:
    raw = str(block or "ONS").upper().strip()
    aliases = {"R_TRIG": "OSR", "RTRIG": "OSR", "F_TRIG": "OSF", "FTRIG": "OSF", "OSRI": "OSR", "OSFI": "OSF"}
    raw = aliases.get(raw, raw)
    return raw if raw in ONESHOT_BLOCKS else "ONS"


def clean_note(value: object) -> str:
    """Instruction note: single line, trimmed, capped (prints stay readable)."""
    text = " ".join(str(value or "").split())
    return text[:NOTE_MAX]


# ---------------------------------------------------------------------------
# v0.3.18 NEW-9: IEC 61131-3 literals (timer PT durations, counter PV integers) and
# tag references. Never defaults to 0: anything unparseable raises ValueError.
# ---------------------------------------------------------------------------
import re as _re_iec
from fractions import Fraction as _Fraction

_IEC_IDENT_RE = _re_iec.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_IEC_KEYWORDS = {"TRUE", "FALSE", "NOT", "AND", "OR", "XOR", "MOD"}
_DUR_PREFIX_RE = _re_iec.compile(r"^(?:LTIME|TIME|LT|T)#(.*)$", _re_iec.IGNORECASE | _re_iec.DOTALL)
_DUR_PART_RE = _re_iec.compile(
    r"(\d(?:_?\d)*)(?:\.(\d(?:_?\d)*))?(ms|us|ns|d|h|m|s)(_?)", _re_iec.IGNORECASE
)
_DUR_UNIT_MS = {
    "d": _Fraction(86_400_000), "h": _Fraction(3_600_000), "m": _Fraction(60_000),
    "s": _Fraction(1000), "ms": _Fraction(1), "us": _Fraction(1, 1000), "ns": _Fraction(1, 1_000_000),
}
_DUR_ORDER = ["d", "h", "m", "s", "ms", "us", "ns"]
_INT_TYPES = (
    "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT", "BYTE", "WORD", "DWORD", "LWORD",
)
_INT_TYPE_BITS = {  # v0.3.19 (Audit P3-I): (bits, signed) for typed-literal range checks
    "SINT": (8, True), "INT": (16, True), "DINT": (32, True), "LINT": (64, True),
    "USINT": (8, False), "UINT": (16, False), "UDINT": (32, False), "ULINT": (64, False),
    "BYTE": (8, False), "WORD": (16, False), "DWORD": (32, False), "LWORD": (64, False),
}
_INT_RE = _re_iec.compile(
    r"^(?:(?P<typ>[A-Za-z]+)#)?(?:(?P<base>2|8|16)#(?P<bdig>[0-9A-Fa-f](?:_?[0-9A-Fa-f])*)"
    r"|(?P<sign>[+-])?(?P<dec>\d(?:_?\d)*))$"
)


def is_tag_reference(text: object) -> bool:
    """True for an IEC identifier (optionally dotted, e.g. ``Recipe.Delay``)."""
    t = str(text if text is not None else "").strip()
    return bool(t) and bool(_IEC_IDENT_RE.fullmatch(t)) and t.upper() not in _IEC_KEYWORDS


def _iec_interval_ms(body: str, original: str) -> _Fraction:
    text = body.strip()
    if not text:
        raise ValueError(f"duration {original!r} has no value")
    pos = 0
    total = _Fraction(0)
    last_rank = -1
    parts = 0
    had_fraction = False
    while pos < len(text):
        m = _DUR_PART_RE.match(text, pos)
        if not m:
            raise ValueError(f"duration {original!r} is not a valid IEC 61131-3 TIME literal")
        if had_fraction:
            raise ValueError(f"duration {original!r}: only the last unit may have a fraction")
        unit = m.group(3).lower()
        rank = _DUR_ORDER.index(unit)
        if rank <= last_rank:
            raise ValueError(f"duration {original!r}: units must go from largest to smallest (d h m s ms)")
        last_rank = rank
        whole = int(m.group(1).replace("_", ""))
        frac = m.group(2)
        value = _Fraction(whole)
        if frac is not None:
            digits = frac.replace("_", "")
            value += _Fraction(int(digits), 10 ** len(digits))
            had_fraction = True
        total += value * _DUR_UNIT_MS[unit]
        parts += 1
        pos = m.end()
        if m.group(4) and pos >= len(text):
            raise ValueError(f"duration {original!r} ends with '_'")
    if not parts:
        raise ValueError(f"duration {original!r} is not a valid IEC 61131-3 TIME literal")
    return total


TIME_MAX_MS = 2_147_483_647  # v0.3.19: IEC TIME (32-bit ms) = T#24d20h31m23s647ms


def parse_iec_duration_ms(text: object, *, allow_bare: bool = True) -> int:
    """Parse an IEC 61131-3 duration (``T#1m30s``, ``TIME#5s``, ``t#1h``, ``T#5s_500ms``,
    ``T#1.5s``, ``T#1d2h``, optional sign) to whole milliseconds.

    ``allow_bare`` (Cabinet Studio back-compat) also accepts a plain decimal integer
    (milliseconds) or a bare interval such as ``5s``. Raises ValueError for anything else,
    for negative durations (a timer preset cannot be negative) and for values that are not
    a whole number of milliseconds. Never returns a default."""
    original = str(text if text is not None else "").strip()
    s = original.replace(" ", "")
    if not s:
        raise ValueError("empty duration")
    if not s.isascii():
        # v0.3.19 (Audit P3-I): Python's \d also matches non-ASCII digits (T#\u0665s was 5 s)
        raise ValueError(f"{original!r} contains non-ASCII characters; not an IEC 61131-3 TIME literal")
    m = _DUR_PREFIX_RE.match(s)
    sign = 1
    if m:
        body = m.group(1)
        if body[:1] and body[:1] in "+-":
            sign = -1 if body[0] == "-" else 1
            body = body[1:]
        if not body:
            raise ValueError(f"{original!r} is not an IEC 61131-3 TIME literal (no interval after '#')")
        total = _iec_interval_ms(body, original)
    elif allow_bare and _re_iec.fullmatch(r"\d(?:_?\d)*", s):
        total = _Fraction(int(s.replace("_", "")))
    elif allow_bare and _DUR_PART_RE.match(s):
        total = _iec_interval_ms(s, original)
    else:
        raise ValueError(f"{original!r} is not an IEC 61131-3 TIME literal (e.g. T#1m30s)")
    total *= sign
    if total < 0:
        raise ValueError(f"duration {original!r} is negative; a timer preset cannot be negative")
    if total.denominator != 1:
        raise ValueError(f"duration {original!r} is not a whole number of milliseconds")
    if total > TIME_MAX_MS:
        # v0.3.19 (Deflector P3-b): IEC TIME / DINT milliseconds range, T#24d20h31m23s647ms.
        raise ValueError(
            f"duration {original!r} = {int(total)} ms is above the maximum timer preset "
            f"{TIME_MAX_MS} ms (T#24d20h31m23s647ms, the 32-bit TIME range)"
        )
    return int(total)


def parse_iec_int(text: object) -> int:
    """Parse an IEC 61131-3 integer literal: ``42``, ``-5``, ``1_000``, ``16#0A``, ``8#17``,
    ``2#1010_0101``, typed ``INT#5`` / ``DINT#16#FF``. Raises ValueError otherwise."""
    original = str(text if text is not None else "").strip()
    if not original.isascii():
        # v0.3.19 (Audit P3-I): no non-ASCII digits
        raise ValueError(f"{original!r} contains non-ASCII characters; not an IEC 61131-3 integer literal")
    m = _INT_RE.match(original)
    if not m:
        raise ValueError(f"{original!r} is not an IEC 61131-3 integer literal")
    typ = (m.group("typ") or "").upper()
    if typ and typ not in _INT_TYPES:
        raise ValueError(f"{original!r}: {typ}# is not an integer type")
    if m.group("base"):
        value = int(m.group("bdig").replace("_", ""), int(m.group("base")))
        if typ and value >= (1 << _INT_TYPE_BITS[typ][0]):
            raise ValueError(f"{original!r} does not fit in {typ} ({_INT_TYPE_BITS[typ][0]} bits)")
        if typ and _INT_TYPE_BITS[typ][1] and value >= (1 << (_INT_TYPE_BITS[typ][0] - 1)):
            # SINT#16#FF is -1 as a bit pattern on most PLCs but 255 as a number: ambiguous.
            raise ValueError(
                f"{original!r} = {value} is above the {typ} maximum {(1 << (_INT_TYPE_BITS[typ][0] - 1)) - 1}; "
                "a signed type read as a bit pattern would be negative, so it is ambiguous"
            )
        return value
    value = int(m.group("dec").replace("_", ""))
    value = -value if m.group("sign") == "-" else value
    if typ:
        # v0.3.19 (Audit P3-I): typed literal must fit its type (SINT#200 refused)
        bits, signed = _INT_TYPE_BITS[typ]
        lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        if not lo <= value <= hi:
            raise ValueError(f"{original!r} = {value} is outside the {typ} range {lo}..{hi}")
    return value


def numeric_literal_value(token: object) -> float | None:
    """Value of a numeric literal operand (decimal / float / 0x.. / IEC 16#..), else None."""
    raw = str(token if token is not None else "").strip()
    if not raw:
        return None
    try:
        if raw.lower().startswith("0x"):
            return float(int(raw, 16))
        return float(raw)
    except ValueError:
        pass
    if "#" in raw:
        try:
            return float(parse_iec_int(raw))
        except ValueError:
            return None
    return None


def preset_tag_of(el: dict[str, Any] | None) -> str:
    """v0.3.18: the tag a timer PT / counter PV is read from ('' for a literal preset)."""
    if not isinstance(el, dict):
        return ""
    k = str(el.get("kind") or "").lower()
    key = "pt_tag" if k == "timer" else "pv_tag" if k == "counter" else ""
    return str(el.get(key) or "").strip() if key else ""


def clamp_counter(value: object) -> int:
    try:
        num = int(float(value or 0))
    except (TypeError, ValueError):
        num = 0
    return max(COUNTER_MIN, min(COUNTER_MAX, num))


def normalize_counter_block(block: object) -> str:
    blk = str(block or "CTU").upper().strip()
    if blk == "CTUD":
        blk = "CTU"
    if blk in {"RST", "RESET"}:
        blk = "RES"
    if blk in {"LD", "LOAD"}:
        blk = "LOAD"
    return blk if blk in COUNTER_BLOCKS else "CTU"


def split_member(tag: str) -> tuple[str, str]:
    """'C1.DN' -> ('C1', 'DN'); 'PB_Start' -> ('PB_Start', '')."""
    name = (tag or "").strip()
    if "." in name:
        base, _, member = name.rpartition(".")
        if base and member.upper() in MEMBER_SUFFIXES:
            return base, member.upper()
    return name, ""


def new_id(prefix: str = "r") -> str:
    return f"{prefix}{uuid4().hex[:8]}"


def empty_ladder(
    *,
    project_name: str = "",
    variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "format": IR_FORMAT,
        "version": IR_VERSION,
        "dialect": IR_DIALECT,
        "meta": {
            "project": project_name or "",
            "not_a_vendor_format": True,
            "label": "Cabinet Studio Educational Ladder",
        },
        "variables": list(variables or []),
        "rungs": [],
    }


def _contact_el(tag: str, normally_closed: bool = False) -> dict[str, Any]:
    return {
        "kind": "contact",
        "var": (tag or "").strip(),
        "form": "NC" if normally_closed else "NO",
    }


def _coil_el(tag: str, negated: bool = False, form: str | None = None) -> dict[str, Any]:
    coil_form = form or ("negated" if negated else "normal")
    return {
        "kind": "coil",
        "var": (tag or "").strip(),
        "form": coil_form,
    }


def _timer_el(tag: str, block: str = "TON", pt_ms: int = 0) -> dict[str, Any]:
    blk = str(block or "TON").upper()
    if blk not in {"TON", "TOF", "RTO"}:
        blk = "TON"
    return {
        "kind": "timer",
        "var": (tag or "").strip(),
        "block": blk,
        "pt_ms": max(0, int(pt_ms or 0)),
    }


def _counter_el(tag: str, block: str = "CTU", pv: int = 0) -> dict[str, Any]:
    blk = normalize_counter_block(block)
    return {
        "kind": "counter",
        "var": (tag or "").strip(),
        "block": blk,
        "pv": clamp_counter(pv) if blk in COUNTER_OWNER_BLOCKS or blk == "LOAD" else 0,
    }


def _oneshot_el(block: str, storage: str, output: str = "") -> dict[str, Any]:
    blk = normalize_oneshot_block(block)
    out: dict[str, Any] = {"kind": "oneshot", "block": blk, "var": (storage or "").strip()}
    if blk in ONESHOT_OUTPUT_BLOCKS:
        out["output"] = (output or "").strip()
    return out



def normalize_routine_name(name: object) -> str:
    """Validate an educational routine / SBR name (Main reserved for program.rungs)."""
    text = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in str(name or "").strip())
    text = text.strip("_")[:ROUTINE_NAME_MAX]
    if not text:
        return ""
    if text.lower() == "main":
        return "Main"
    return text


def _jsr_el(target: str) -> dict[str, Any]:
    return {"kind": "jsr", "target": normalize_routine_name(target)}


def _sbr_el(name: str) -> dict[str, Any]:
    return {"kind": "sbr", "name": normalize_routine_name(name)}


def _ret_el() -> dict[str, Any]:
    return {"kind": "ret"}


def normalize_compare_op(op: object) -> str:
    raw = str(op or "EQU").upper().strip()
    aliases = {
        "EQ": "EQU", "==": "EQU", "=": "EQU",
        "NE": "NEQ", "<>": "NEQ", "!=": "NEQ",
        "GT": "GRT", ">": "GRT",
        "LT": "LES", "<": "LES",
        "GE": "GEQ", ">=": "GEQ",
        "LE": "LEQ", "<=": "LEQ",
        "LIMIT": "LIM", "LIMITED": "LIM",
        "MASKED_EQ": "MEQ", "MASK_EQ": "MEQ", "MXEQ": "MEQ",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in COMPARE_OPS else "EQU"


def normalize_math_op(op: object) -> str:
    raw = str(op or "ADD").upper().strip()
    aliases = {
        "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV",
        "MOVE": "MOV", "COMPUTE": "CPT",
        "&": "AND", "|": "OR", "^": "XOR", "~": "NOT", "BAND": "AND", "BOR": "OR", "BXOR": "XOR", "BNOT": "NOT",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in MATH_OPS else "ADD"


def clamp_numeric(value: object) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = 0.0
    if num > NUMERIC_MAX:
        return float(NUMERIC_MAX)
    if num < NUMERIC_MIN:
        return float(NUMERIC_MIN)
    return num


def to_dint(value: object) -> int:
    """Educational 32-bit signed integer (Studio DINT-style) for bitwise / MEQ."""
    try:
        num = int(float(value))
    except (TypeError, ValueError):
        num = 0
    # wrap to signed 32-bit
    num = num & 0xFFFFFFFF
    if num >= 0x80000000:
        num -= 0x100000000
    return num


INTEGER_NUMERIC_TYPES = {"DINT", "INT", "SINT", "UDINT", "UINT", "USINT"}


def coerce_numeric(value: object, dest_type: object = "REAL", *, op: object = "") -> float:
    """Apply destination-type rules (CCW / Micro800 educational).

    - REAL / LREAL: saturating float clamp.
    - DINT / INT family:
      - MOV: round-half-away-from-zero then wrap to signed 32-bit (Logix MOV→DINT).
      - DIV / CPT / arithmetic: truncate toward zero, then wrap (not saturate).
    Overflow wraps (2147483647*2 → -2), matching Logix/CCW DINT wrap + overflow flag elsewhere.
    """
    dtype = str(dest_type or "REAL").upper().strip() or "REAL"
    mop = str(op or "").upper().strip()
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = 0.0
    if dtype not in INTEGER_NUMERIC_TYPES:
        return clamp_numeric(num)
    if mop == "MOV":
        # Round half away from zero (3.5→4, -3.5→-4); matches common Logix MOV→DINT.
        if num >= 0:
            num = float(int(num + 0.5))
        else:
            num = float(int(num - 0.5))
    else:
        # Truncate toward zero for DIV / CPT / ADD / MUL into integer dest.
        num = float(int(num))
    return float(to_dint(num))


_CPT_TOKEN_RE = __import__("re").compile(
    r"""
    \s*(?:
        (?P<iec>(?:[A-Za-z]+\#)?(?:2|8|16)\#[0-9A-Fa-f](?:_?[0-9A-Fa-f])*|[A-Za-z]+\#\d(?:_?\d)*) |
        (?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?) |
        (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?) |
        (?P<op>\*\*|[+\-*/()]) |
        (?P<bad>.)
    )
    """,
    __import__("re").VERBOSE,
)


def tokenize_cpt(expression: str) -> list[tuple[str, str]]:
    """Tokenize a CPT expression into (kind, value) pairs. Raises ValueError on junk."""
    text = str(expression or "").strip()
    if not text:
        raise ValueError("empty CPT expression")
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _CPT_TOKEN_RE.match(text, pos)
        if not m:
            raise ValueError(f"bad CPT token near {text[pos:pos+8]!r}")
        pos = m.end()
        if m.group("iec") is not None:
            # v0.3.18 (P3-E): IEC based / typed integer literals, e.g. 16#FF, INT#5.
            tokens.append(("num", str(parse_iec_int(m.group("iec")))))
        elif m.group("num") is not None:
            tokens.append(("num", m.group("num")))
        elif m.group("ident") is not None:
            tokens.append(("ident", m.group("ident")))
        elif m.group("op") is not None:
            op = m.group("op")
            if op == "**":
                raise ValueError("** not supported in educational CPT (use * twice if needed)")
            tokens.append(("op", op))
        else:
            bad = m.group("bad")
            if bad and not bad.isspace():
                raise ValueError(f"unsupported CPT character {bad!r}")
    return tokens


def cpt_expression_error(expression: object) -> str:
    """v0.3.17: '' when a CPT expression parses; else a short reason (empty / malformed).

    Used by Verify (F7, error) and by the simulator gate (refuse to run). The expression
    text itself is never rewritten."""
    text = str(expression if expression is not None else "").strip()
    if not text:
        return "CPT expression is empty"
    try:
        eval_cpt_expression(text, lambda _tok: 1.0, strict=True)
    except ValueError as exc:
        return f"CPT expression {text!r} cannot be parsed ({exc})"
    except Exception as exc:  # v0.3.18 (Deflector P3-2): fail closed
        return f"CPT expression {text!r} could not be checked ({type(exc).__name__})"
    return ""


def eval_cpt_expression(expression: str, read_number, *, strict: bool = False) -> float:
    """Evaluate CPT with educational precedence: unary -, then */ , then +- ; parentheses.

    ``read_number`` is a callable(str) -> float for tag / literal resolution.
    Safe: no Python eval — recursive descent over a restricted token set only.
    ``strict`` (v0.3.18, used by Verify / the sim gate): a division by a CONSTANT zero
    (e.g. ``1/0``, ``A/(2-2)``) raises ValueError instead of evaluating to 0.
    """
    tokens = tokenize_cpt(expression)
    i = 0

    def peek() -> tuple[str, str] | None:
        return tokens[i] if i < len(tokens) else None

    def take(expected: str | None = None) -> tuple[str, str]:
        nonlocal i
        tok = peek()
        if tok is None:
            raise ValueError("unexpected end of CPT expression")
        if expected is not None and tok[1] != expected:
            raise ValueError(f"expected {expected!r}, got {tok[1]!r}")
        i += 1
        return tok

    # Each parse step returns (value, is_constant).
    def parse_primary() -> tuple[float, bool]:
        tok = peek()
        if tok is None:
            raise ValueError("expected value in CPT")
        kind, val = tok
        if kind == "num":
            take()
            return float(val), True
        if kind == "ident":
            take()
            return float(read_number(val)), False
        if kind == "op" and val == "(":
            take()
            v = parse_expr()
            take(")")
            return v
        raise ValueError(f"unexpected token {val!r} in CPT")

    def parse_unary() -> tuple[float, bool]:
        tok = peek()
        if tok and tok[0] == "op" and tok[1] == "-":
            take()
            v, c = parse_unary()
            return -v, c
        if tok and tok[0] == "op" and tok[1] == "+":
            take()
            return parse_unary()
        return parse_primary()

    def parse_term() -> tuple[float, bool]:
        v, c = parse_unary()
        while True:
            tok = peek()
            if not tok or tok[0] != "op" or tok[1] not in {"*", "/"}:
                return v, c
            op = take()[1]
            rhs, rc = parse_unary()
            if op == "*":
                v = v * rhs
            else:
                if rhs == 0 and rc and strict:
                    raise ValueError("division by a constant zero")
                v = 0.0 if rhs == 0 else v / rhs
            c = c and rc

    def parse_expr() -> tuple[float, bool]:
        v, c = parse_term()
        while True:
            tok = peek()
            if not tok or tok[0] != "op" or tok[1] not in {"+", "-"}:
                return v, c
            op = take()[1]
            rhs, rc = parse_term()
            v = v + rhs if op == "+" else v - rhs
            c = c and rc

    result, _const = parse_expr()
    if peek() is not None:
        raise ValueError(f"trailing CPT tokens starting at {peek()!r}")
    return clamp_numeric(result)


def _compare_el(op: str, source_a: str, source_b: str, source_c: str = "") -> dict[str, Any]:
    mop = normalize_compare_op(op)
    out = {
        "kind": "compare",
        "op": mop,
        "source_a": str(source_a or "").strip(),
        "source_b": str(source_b or "").strip(),
    }
    # Two-operand compares have no IN3 pin; a stray C would export a block the importer must refuse.
    if mop in COMPARE_THREE_OPS:
        out["source_c"] = str(source_c or "").strip()
    return out


def _math_el(
    op: str,
    dest: str,
    source_a: str = "",
    source_b: str = "",
    expression: str = "",
) -> dict[str, Any]:
    mop = normalize_math_op(op)
    out = {
        "kind": "math",
        "op": mop,
        "dest": str(dest or "").strip(),
        "source_a": str(source_a or "").strip(),
        "source_b": str(source_b or "").strip(),
    }
    if mop == "CPT":
        out["expression"] = str(expression or source_a or "").strip()
    return out



def _clean_logic_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize one logic element (keeps an optional instruction note ``desc``)."""
    cleaned = _clean_logic_item_core(item)
    if cleaned is None or not isinstance(item, dict):
        return cleaned
    note = clean_note(item.get("desc") or item.get("note") or "")
    if note and cleaned.get("kind") != "or":
        cleaned["desc"] = note
    return cleaned


def _clean_logic_item_core(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize one logic element; OR branches may nest further OR groups."""
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind") or "").lower()
    if kind in {"ons", "osr", "osf", "r_trig", "rtrig", "f_trig", "ftrig"}:
        item = {**item, "block": normalize_oneshot_block(kind)}
        kind = "oneshot"
    if kind == "oneshot":
        storage = str(item.get("var") or item.get("storage") or item.get("tag") or "").strip()
        if not storage:
            return None
        return _oneshot_el(
            str(item.get("block") or "ONS"),
            storage,
            str(item.get("output") or item.get("output_bit") or ""),
        )
    if kind == "contact":
        var = str(item.get("var") or item.get("tag") or "").strip()
        if not var:
            return None
        return {
            "kind": "contact",
            "var": var,
            "form": "NC" if str(item.get("form", "NO")).upper() == "NC" or bool(item.get("normally_closed")) else "NO",
        }
    if kind == "or":
        branches: list[list[dict[str, Any]]] = []
        for branch in item.get("branches") or []:
            if not isinstance(branch, list):
                continue
            cleaned: list[dict[str, Any]] = []
            for sub in branch:
                c = _clean_logic_item(sub if isinstance(sub, dict) else None)
                if c:
                    cleaned.append(c)
            if cleaned:
                branches.append(cleaned)
        if not branches:
            return None
        return {"kind": "or", "branches": branches}
    if kind == "coil":
        var = str(item.get("var") or item.get("tag") or "").strip()
        if not var:
            return None
        form = str(item.get("form") or ("negated" if item.get("negated") or item.get("coil_negated") else "normal")).lower()
        if form not in {"normal", "negated", "set", "reset", "s", "r"}:
            form = "normal"
        return {"kind": "coil", "var": var, "form": form}
    if kind == "timer":
        var = str(item.get("var") or item.get("tag") or "").strip()
        if not var:
            return None
        blk = str(item.get("block") or "TON").upper()
        if blk not in TIMER_BLOCKS:
            blk = "TON"
        t_out: dict[str, Any] = {"kind": "timer", "var": var, "block": blk, "pt_ms": max(0, int(item.get("pt_ms") or 0))}
        # v0.3.18 NEW-9: PT read from a tag (kept as a reference, never turned into 0).
        pt_tag = str(item.get("pt_tag") or "").strip()
        if pt_tag and is_tag_reference(pt_tag):
            t_out["pt_tag"] = pt_tag
        return t_out
    if kind == "counter":
        var = str(item.get("var") or item.get("tag") or "").strip()
        if not var:
            return None
        c_out = _counter_el(var, str(item.get("block") or "CTU"), item.get("pv", item.get("pre", 0)))
        pv_tag = str(item.get("pv_tag") or "").strip()
        if pv_tag and is_tag_reference(pv_tag) and c_out["block"] in (*COUNTER_OWNER_BLOCKS, "LOAD"):
            c_out["pv_tag"] = pv_tag
        return c_out
    if kind == "compare":
        a = str(item.get("source_a") or item.get("a") or item.get("in1") or item.get("test") or "").strip()
        b = str(item.get("source_b") or item.get("b") or item.get("in2") or item.get("low") or item.get("mask") or "").strip()
        c = str(item.get("source_c") or item.get("c") or item.get("in3") or item.get("high") or item.get("compare") or "").strip()
        if not a and not b and not c:
            return None
        return _compare_el(str(item.get("op") or "EQU"), a, b, c)
    if kind == "math":
        dest = str(item.get("dest") or item.get("var") or item.get("tag") or "").strip()
        if not dest:
            return None
        return _math_el(
            str(item.get("op") or "ADD"),
            dest,
            str(item.get("source_a") or item.get("a") or item.get("in1") or ""),
            str(item.get("source_b") or item.get("b") or item.get("in2") or ""),
            str(item.get("expression") or ""),
        )
    if kind == "jsr":
        target = normalize_routine_name(item.get("target") or item.get("routine") or item.get("name") or "")
        if not target or target == "Main":
            return None
        return _jsr_el(target)
    if kind == "sbr":
        name = normalize_routine_name(item.get("name") or item.get("target") or item.get("var") or "")
        if not name:
            return None
        return _sbr_el(name)
    if kind == "ret":
        return _ret_el()
    return None


def clean_elements(elements: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize a full rung element list (allows nested OR + mid-rung coils)."""
    out: list[dict[str, Any]] = []
    for el in elements or []:
        cleaned = _clean_logic_item(el if isinstance(el, dict) else None)
        if cleaned:
            out.append(cleaned)
    return out


def elements_have_nested_or(elements: list[dict[str, Any]] | None) -> bool:
    def walk(els: list) -> bool:
        for el in els or []:
            if not isinstance(el, dict):
                continue
            if str(el.get("kind") or "").lower() != "or":
                continue
            for branch in el.get("branches") or []:
                for item in branch or []:
                    if isinstance(item, dict) and str(item.get("kind") or "").lower() == "or":
                        return True
                    if isinstance(item, dict) and str(item.get("kind") or "").lower() == "or":
                        return True
                if walk(list(branch or [])):
                    return True
        return False
    return walk(list(elements or []))


def elements_have_mid_rung_coil(elements: list[dict[str, Any]] | None) -> bool:
    """True when a coil appears before the final element (or before later logic)."""
    els = list(elements or [])
    coil_indexes = [i for i, e in enumerate(els) if str(e.get("kind") or "").lower() == "coil"]
    if not coil_indexes:
        return False
    last = len(els) - 1
    for i in coil_indexes:
        if i < last:
            # Anything after a coil (contact/or/coil/timer/counter) => mid-rung
            return True
    return False


def elements_have_notes(elements: list[dict[str, Any]] | None) -> bool:
    """True when any element (including inside OR branches) carries a ``desc`` note."""
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        if el.get("desc"):
            return True
        if str(el.get("kind") or "").lower() == "or":
            for branch in el.get("branches") or []:
                if elements_have_notes(list(branch or [])):
                    return True
    return False


def elements_have_oneshot(elements: list[dict[str, Any]] | None) -> bool:
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        if str(el.get("kind") or "").lower() == "oneshot":
            return True
        if str(el.get("kind") or "").lower() == "or":
            for branch in el.get("branches") or []:
                if elements_have_oneshot(list(branch or [])):
                    return True
    return False


def _or_branch_needs_storage(branch: list | None) -> bool:
    """True when a single OR branch cannot be expressed as contact-only classic parallel."""
    items = [i for i in (branch or []) if isinstance(i, dict)]
    if len(items) > 1:
        # Series contacts (or mixed) inside a branch — keep elements for fidelity.
        return True
    for item in items:
        kind = str(item.get("kind") or "").lower()
        if kind == "or":
            return True
        if kind != "contact":
            # coil / timer / counter / math / compare / oneshot / jsr inside OR
            return True
    return False


def elements_have_or_actuators(elements: list[dict[str, Any]] | None) -> bool:
    """True when any OR branch contains a non-contact actuator / box."""
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        if str(el.get("kind") or "").lower() != "or":
            continue
        for branch in el.get("branches") or []:
            for item in branch or []:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "").lower()
                if kind == "or":
                    if elements_have_or_actuators([item]):
                        return True
                elif kind != "contact":
                    return True
    return False


def elements_need_storage(elements: list[dict[str, Any]] | None) -> bool:
    """Program dict should keep full elements when classic parallel/series would lose structure.

    v0.3.11: also force-store contact-before-OR, consecutive ORs, series-in-OR-branch,
    and actuators (coil/timer/counter/math/JSR) inside OR branches.
    """
    els = clean_elements(elements)
    if elements_have_nested_or(els) or elements_have_mid_rung_coil(els):
        return True
    if elements_have_or_actuators(els):
        return True
    or_count = 0
    saw_non_or_before_or = False
    saw_or = False
    for e in els:
        kind = str(e.get("kind") or "").lower()
        if kind == "or":
            or_count += 1
            if saw_non_or_before_or:
                return True  # contact / series ahead of OR
            if or_count > 1:
                return True  # consecutive top-level ORs
            for branch in e.get("branches") or []:
                if _or_branch_needs_storage(list(branch or [])):
                    return True
            saw_or = True
        elif kind in {"compare", "math", "oneshot", "jsr", "sbr", "ret"}:
            return True
        elif kind == "coil" and str(e.get("form") or "").lower() in {"set", "s", "reset", "r"}:
            return True
        elif kind in {"contact", "timer", "counter", "compare", "oneshot", "math"}:
            if not saw_or:
                saw_non_or_before_or = True
            elif kind == "contact":
                # Series contact after OR (seal-in Stop/ES) — force-store; LD walk corrupts it.
                return True
        elif kind == "coil":
            if not saw_or:
                saw_non_or_before_or = True
    if elements_have_notes(els):
        return True
    coils = [e for e in els if str(e.get("kind") or "").lower() == "coil"]
    return len(coils) > 1


def program_rung_to_elements(rung: dict[str, Any]) -> list[dict[str, Any]]:
    """Map one project.program rung into IR element list (series of contact/or/coil).

    Prefer an explicit ``elements`` list when present (nested OR / mid-rung coils).
    Otherwise rebuild from parallel / series / timer / counter / coil_tag.
    """
    if isinstance(rung.get("elements"), list) and rung.get("elements"):
        return clean_elements(rung.get("elements"))

    elements: list[dict[str, Any]] = []
    parallel = list(rung.get("parallel") or [])
    series = list(rung.get("series") or [])
    coil = (rung.get("coil_tag") or "").strip()
    coil_neg = bool(rung.get("coil_negated"))
    mid_coils = list(rung.get("mid_coils") or [])

    if parallel:
        if len(parallel) == 1 and len(parallel[0]) == 1:
            c = parallel[0][0]
            # Branch item may be a nested OR dict (rare in program dict) or contact
            if isinstance(c, dict) and str(c.get("kind") or "").lower() == "or":
                cleaned = _clean_logic_item(c)
                if cleaned:
                    elements.append(cleaned)
            else:
                elements.append(_contact_el(c.get("tag", ""), bool(c.get("normally_closed"))))
        elif len(parallel) == 1:
            for c in parallel[0]:
                if isinstance(c, dict) and str(c.get("kind") or "").lower() == "or":
                    cleaned = _clean_logic_item(c)
                    if cleaned:
                        elements.append(cleaned)
                else:
                    elements.append(_contact_el(c.get("tag", ""), bool(c.get("normally_closed"))))
        else:
            branches: list[list[dict[str, Any]]] = []
            for branch in parallel:
                branch_els: list[dict[str, Any]] = []
                for c in branch:
                    if isinstance(c, dict) and str(c.get("kind") or "").lower() == "or":
                        cleaned = _clean_logic_item(c)
                        if cleaned:
                            branch_els.append(cleaned)
                    elif (c.get("tag") or "").strip():
                        branch_els.append(_contact_el(c.get("tag", ""), bool(c.get("normally_closed"))))
                if branch_els:
                    branches.append(branch_els)
            if len(branches) == 1:
                elements.extend(branches[0])
            elif branches:
                elements.append({"kind": "or", "branches": branches})

    # Mid-rung coils inserted after parallel group, before series (program-dict shorthand)
    for mc in mid_coils:
        if not isinstance(mc, dict):
            continue
        tag = (mc.get("tag") or mc.get("var") or "").strip()
        if not tag:
            continue
        form = str(mc.get("form") or ("negated" if mc.get("negated") else "normal"))
        elements.append(_coil_el(tag, form=form if form in {"normal", "negated", "set", "reset"} else "normal"))

    for c in series:
        tag = (c.get("tag") or "").strip()
        if tag:
            elements.append(_contact_el(tag, bool(c.get("normally_closed"))))

    timer = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
    if timer:
        t_tag = (timer.get("tag") or timer.get("var") or "").strip()
        if t_tag:
            elements.append(
                _timer_el(
                    t_tag,
                    str(timer.get("block") or "TON"),
                    int(timer.get("pt_ms") or 0),
                )
            )

    counter = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
    if counter:
        c_tag = (counter.get("tag") or counter.get("var") or "").strip()
        if c_tag:
            elements.append(
                _counter_el(
                    c_tag,
                    str(counter.get("block") or "CTU"),
                    counter.get("pv", counter.get("pre", 0)),
                )
            )

    if coil:
        elements.append(_coil_el(coil, coil_neg))
    return elements


def elements_to_program_rung(
    elements: list[dict[str, Any]],
    *,
    rung_id: str | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Map IR elements back into the Programming viewer rung shape.

    Simple series/parallel/single-coil rungs keep the classic fields only.
    Nested OR or mid-rung / multi-coil rungs also store ``elements`` (and
    ``mid_coils`` when applicable) so round-trips stay lossless.
    """
    elements = clean_elements(elements)
    parallel: list[list[dict[str, Any]]] = []
    series: list[dict[str, Any]] = []
    coil_tag = ""
    coil_negated = False
    timer: dict[str, Any] | None = None
    counter: dict[str, Any] | None = None
    mid_coils: list[dict[str, Any]] = []
    seen_or = False
    trailing_coil_indexes: list[int] = []

    def contact_from(item: dict[str, Any]) -> dict[str, Any] | None:
        tag = (item.get("var") or "").strip()
        if not tag:
            return None
        return {
            "tag": tag,
            "normally_closed": str(item.get("form", "NO")).upper() == "NC",
        }

    def branch_to_program(branch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Flatten one OR branch for the classic parallel field (contacts only;
        nested OR groups are kept as kind=or dicts inside the branch list)."""
        out: list[dict[str, Any]] = []
        for item in branch:
            kind = str(item.get("kind") or "").lower()
            if kind == "contact":
                c = contact_from(item)
                if c:
                    out.append(c)
            elif kind == "or":
                out.append({"kind": "or", "branches": item.get("branches") or []})
        return out

    for idx, el in enumerate(elements):
        kind = (el.get("kind") or "").strip().lower()
        if kind == "or":
            seen_or = True
            for branch in el.get("branches") or []:
                contacts = branch_to_program(list(branch))
                if contacts:
                    parallel.append(contacts)
        elif kind == "contact":
            contact = contact_from(el)
            if not contact:
                continue
            if not seen_or and not parallel and not series and not mid_coils:
                parallel.append([contact])
            elif not seen_or and len(parallel) == 1 and not series and not mid_coils:
                parallel[0].append(contact)
            else:
                series.append(contact)
        elif kind == "coil":
            trailing_coil_indexes.append(idx)
            form = str(el.get("form", "normal")).lower()
            tag = (el.get("var") or "").strip()
            # Defer assigning coil_tag: last coil wins for classic field
            coil_tag = tag
            coil_negated = form in {"negated", "not", "nc"}
        elif kind == "timer":
            t_tag = (el.get("var") or "").strip()
            if t_tag:
                blk = str(el.get("block") or "TON").upper()
                if blk not in {"TON", "TOF", "RTO"}:
                    blk = "TON"
                timer = {
                    "tag": t_tag,
                    "block": blk,
                    "pt_ms": max(0, int(el.get("pt_ms") or 0)),
                }
        elif kind == "counter":
            c_tag = (el.get("var") or "").strip()
            if c_tag:
                c_el = _counter_el(c_tag, str(el.get("block") or "CTU"), el.get("pv", el.get("pre", 0)))
                counter = {"tag": c_tag, "block": c_el["block"], "pv": c_el["pv"]}
        elif kind in {"compare", "math", "oneshot", "jsr", "sbr", "ret"}:
            # Full elements list is required; classic fields alone cannot express these.
            pass

    # Mid-rung coils: every coil except the final trailing one (and any after last logic)
    if elements_have_mid_rung_coil(elements) and trailing_coil_indexes:
        last_coil_i = trailing_coil_indexes[-1]
        for i in trailing_coil_indexes:
            if i >= last_coil_i:
                continue
            el = elements[i]
            mid_coils.append(
                {
                    "tag": (el.get("var") or "").strip(),
                    "form": str(el.get("form") or "normal").lower(),
                    "negated": str(el.get("form") or "").lower() in {"negated", "not", "nc"},
                }
            )
        # Last coil is coil_tag
        last = elements[last_coil_i]
        coil_tag = (last.get("var") or "").strip()
        coil_negated = str(last.get("form", "normal")).lower() in {"negated", "not", "nc"}

    contact_tag = ""
    normally_closed = False
    flat = []
    for branch in parallel:
        for item in branch:
            if isinstance(item, dict) and item.get("tag"):
                flat.append(item)
    flat.extend(series)
    if flat:
        contact_tag = flat[0].get("tag", "")
        normally_closed = bool(flat[0].get("normally_closed"))

    out = {
        "id": (rung_id or new_id("r")).strip() or new_id("r"),
        "parallel": parallel,
        "series": series,
        "coil_tag": coil_tag,
        "coil_negated": bool(coil_negated),
        "comment": (comment or "").strip(),
        "contact_tag": contact_tag,
        "normally_closed": normally_closed,
    }
    if timer:
        out["timer"] = timer
    if counter:
        out["counter"] = counter
    if mid_coils:
        out["mid_coils"] = mid_coils
    # v0.3.11 lossless guard (same idea as ladder_tools._rebuild_rung):
    # always store elements when classic fields alone would change the logic.
    if elements_need_storage(elements):
        out["elements"] = elements
    elif elements:
        rebuilt = clean_elements(program_rung_to_elements({k: v for k, v in out.items() if k != "elements"}))
        if rebuilt != elements:
            out["elements"] = elements
    return out


def variables_from_program(
    program: dict[str, Any] | None,
    *,
    devices: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build IR variable table from rungs + optional cabinet device tags."""
    seen: dict[str, dict[str, Any]] = {}
    for device in devices or []:
        tag = (device.get("tag") or "").strip()
        if not tag or tag in seen:
            continue
        type_id = (device.get("type_id") or "").lower()
        cls = "internal"
        if type_id in {
            "pushbutton",
            "estop",
            "selector",
            "limit_switch",
            "proximity",
            "photoeye",
            "sensor",
            "light_curtain",
        } or "sensor" in type_id or "button" in type_id:
            cls = "input"
        elif type_id in {
            "contactor",
            "relay",
            "solenoid",
            "motor",
            "lamp",
            "pilot_light",
            "valve",
            "horn",
        } or "relay" in type_id or "coil" in type_id:
            cls = "output"
        addr = (device.get("io_address") or "").strip()
        seen[tag] = {
            "name": tag,
            "class": cls,
            "type": "BOOL",
            "address": addr if addr and addr.lower() != "n/a" else "",
        }

    # Timer / counter instance names: their members (C1.DN, T1.TT) are not inputs.
    fb_names: set[str] = set()
    for rung in (program or {}).get("rungs") or []:
        for key in ("timer", "counter"):
            blk = rung.get(key) if isinstance(rung.get(key), dict) else None
            if blk and (blk.get("tag") or blk.get("var") or "").strip():
                fb_names.add((blk.get("tag") or blk.get("var") or "").strip())
        for el in rung.get("elements") or []:
            if isinstance(el, dict) and str(el.get("kind") or "").lower() in {"timer", "counter"}:
                name = (el.get("var") or el.get("tag") or "").strip()
                if name:
                    fb_names.add(name)

    def _is_member_ref(tag: str) -> bool:
        base, member = split_member(tag)
        return bool(member) and base in fb_names

    def _note_contact_tag(tag: str) -> None:
        tag = (tag or "").strip()
        if tag and tag not in seen and not _is_member_ref(tag) and tag not in fb_names:
            seen[tag] = {"name": tag, "class": "input", "type": "BOOL", "address": ""}

    def _walk_logic_for_vars(els: list) -> None:
        for el in els or []:
            if not isinstance(el, dict):
                continue
            kind = str(el.get("kind") or "").lower()
            if kind == "contact":
                _note_contact_tag(str(el.get("var") or el.get("tag") or ""))
            elif kind == "or":
                for branch in el.get("branches") or []:
                    _walk_logic_for_vars(list(branch))
            elif kind == "oneshot":
                storage = str(el.get("var") or "").strip()
                if storage:
                    if storage not in seen or seen[storage].get("class") == "input":
                        seen[storage] = {"name": storage, "class": "internal", "type": "BOOL", "address": ""}
                output = str(el.get("output") or "").strip()
                if output:
                    if output not in seen:
                        seen[output] = {"name": output, "class": "output", "type": "BOOL", "address": ""}
                    elif seen[output].get("class") == "input":
                        seen[output]["class"] = "output"
            elif kind == "coil":
                tag = str(el.get("var") or el.get("tag") or "").strip()
                if tag:
                    if tag not in seen:
                        seen[tag] = {"name": tag, "class": "output", "type": "BOOL", "address": ""}
                    elif seen[tag].get("class") == "input":
                        seen[tag]["class"] = "output"
            elif kind == "math":
                # v0.3.12 P1-6: UI math destinations default to DINT (CCW integer semantics).
                dest = str(el.get("dest") or "").strip()
                if dest and not _looks_numeric_literal(dest):
                    if dest not in seen or seen[dest].get("class") in {"input", "output", "internal"}:
                        if dest not in seen or seen[dest].get("type") == "BOOL":
                            seen[dest] = {
                                "name": dest,
                                "class": "numeric",
                                "type": "DINT",
                                "address": "",
                            }
                for src in (el.get("source_a"), el.get("source_b"), el.get("expression")):
                    s = str(src or "").strip()
                    if not s or _looks_numeric_literal(s) or any(ch in s for ch in "+-*/()"):
                        continue
                    if s not in seen:
                        seen[s] = {"name": s, "class": "numeric", "type": "DINT", "address": ""}
            elif kind == "compare":
                for src in (el.get("source_a"), el.get("source_b"), el.get("source_c")):
                    s = str(src or "").strip()
                    if not s or _looks_numeric_literal(s):
                        continue
                    if s not in seen:
                        seen[s] = {"name": s, "class": "numeric", "type": "DINT", "address": ""}
            elif kind in {"timer", "counter"}:
                # v0.3.18 NEW-9: a PT / PV preset tag is a numeric (DINT, ms for PT) tag.
                s = preset_tag_of(el)
                if s and not split_member(s)[1] and (s not in seen or seen[s].get("type") == "BOOL"):
                    seen[s] = {"name": s, "class": "numeric", "type": "DINT", "address": ""}

    for rung in (program or {}).get("rungs") or []:
        if isinstance(rung.get("elements"), list) and rung.get("elements"):
            _walk_logic_for_vars(rung.get("elements"))
        for contact in list(rung.get("series") or []):
            _note_contact_tag(contact.get("tag", ""))
        for branch in rung.get("parallel") or []:
            for contact in branch:
                if isinstance(contact, dict) and str(contact.get("kind") or "").lower() == "or":
                    _walk_logic_for_vars([contact])
                else:
                    _note_contact_tag((contact.get("tag") if isinstance(contact, dict) else "") or "")
        for mc in rung.get("mid_coils") or []:
            if isinstance(mc, dict):
                tag = (mc.get("tag") or mc.get("var") or "").strip()
                if tag:
                    if tag not in seen:
                        seen[tag] = {"name": tag, "class": "output", "type": "BOOL", "address": ""}
                    elif seen[tag].get("class") == "input":
                        seen[tag]["class"] = "output"
        coil = (rung.get("coil_tag") or "").strip()
        if coil:
            if coil not in seen:
                seen[coil] = {"name": coil, "class": "output", "type": "BOOL", "address": ""}
            elif seen[coil].get("class") == "input":
                # Coil use upgrades class to output for sim feedback.
                seen[coil]["class"] = "output"
        tmr = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
        if tmr:
            t_tag = (tmr.get("tag") or tmr.get("var") or "").strip()
            if t_tag:
                blk = str(tmr.get("block") or "TON").upper()
                if blk not in {"TON", "TOF", "RTO"}:
                    blk = "TON"
                seen[t_tag] = {
                    "name": t_tag,
                    "class": "timer",
                    "type": blk,
                    "address": "",
                    "pt_ms": max(0, int(tmr.get("pt_ms") or 0)),
                }
        ctr = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
        if ctr:
            c_tag = (ctr.get("tag") or ctr.get("var") or "").strip()
            if c_tag:
                blk = normalize_counter_block(ctr.get("block"))
                existing = seen.get(c_tag)
                if blk in COUNTER_OWNER_BLOCKS:
                    seen[c_tag] = {
                        "name": c_tag,
                        "class": "counter",
                        "type": blk,
                        "address": "",
                        "pv": clamp_counter(ctr.get("pv", ctr.get("pre", 0))),
                    }
                elif not existing or existing.get("class") != "counter":
                    # RES / LOAD before (or without) the owning CTU/CTD rung.
                    seen[c_tag] = {
                        "name": c_tag,
                        "class": "counter",
                        "type": "CTU",
                        "address": "",
                        "pv": clamp_counter(ctr.get("pv", 0)) if blk == "LOAD" else 0,
                    }
    return list(seen.values())


def _attach_descriptions(
    variables: list[dict[str, Any]],
    program: dict[str, Any],
    devices: list[dict[str, str]] | None,
) -> None:
    """v0.3.7 tag database: user description wins, else the cabinet device text.

    Described numeric tags (compare/math operands) that are not yet in the table are
    declared as REAL so their description survives PLCopen interchange.
    """
    user = program.get("tag_descriptions") if isinstance(program.get("tag_descriptions"), dict) else {}
    dev_text = {
        str(d.get("tag") or "").strip(): str(d.get("description") or d.get("function") or "").strip()
        for d in devices or []
        if str(d.get("tag") or "").strip()
    }
    names = set()
    for var in variables:
        name = str(var.get("name") or "")
        names.add(name)
        text = clean_note(user.get(name) or dev_text.get(name) or "")
        if text:
            var["description"] = text
    for name, text in (user or {}).items():
        name = str(name or "").strip()
        if name and name not in names and clean_note(text) and not _looks_numeric_literal(name):
            variables.append(
                {"name": name, "class": "numeric", "type": "REAL", "address": "", "description": clean_note(text)}
            )


def program_to_ladder_ir(
    program: dict[str, Any] | None,
    *,
    project_name: str = "",
    devices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Convert project.program into cabinet-studio-ladder IR."""
    data = program or {}
    variables = variables_from_program(data, devices=devices)
    _attach_descriptions(variables, data, devices)
    ladder = empty_ladder(project_name=project_name, variables=variables)
    rungs_out: list[dict[str, Any]] = []
    for index, rung in enumerate(data.get("rungs") or [], start=1):
        rid = str(rung.get("id") or index)
        rungs_out.append(
            {
                "id": rid,
                "comment": (rung.get("comment") or "").strip(),
                "elements": program_rung_to_elements(rung),
            }
        )
    ladder["rungs"] = rungs_out
    # Additional named routines (v0.3.8) — Main stays in ladder["rungs"].
    routines_out: dict[str, list[dict[str, Any]]] = {}
    raw_routines = data.get("routines") if isinstance(data.get("routines"), dict) else {}
    for rname, rrungs in (raw_routines or {}).items():
        name = normalize_routine_name(rname)
        if not name or name == "Main" or not isinstance(rrungs, list):
            continue
        built = []
        for index, rung in enumerate(rrungs, start=1):
            if not isinstance(rung, dict):
                continue
            rid = str(rung.get("id") or f"{name}_{index}")
            built.append(
                {
                    "id": rid,
                    "comment": (rung.get("comment") or "").strip(),
                    "elements": program_rung_to_elements(rung),
                }
            )
        if built:
            routines_out[name] = built
    if routines_out:
        ladder["routines"] = routines_out
    aliases = normalize_tag_aliases(data.get("tag_aliases"))
    if aliases:
        ladder["meta"]["tag_aliases"] = aliases
    # Preserve answers/hmi as opaque meta for round-trip convenience (not IEC).
    if data.get("answers"):
        ladder["meta"]["answers"] = dict(data["answers"])
    if data.get("hmi_items"):
        ladder["meta"]["hmi_items"] = list(data["hmi_items"])
    return ladder


def ladder_ir_to_program(ladder: dict[str, Any] | None) -> dict[str, Any]:
    """Convert IR back into project.program shape (answers/hmi from meta when present)."""
    ladder = ladder or {}
    rungs = []
    for index, rung in enumerate(ladder.get("rungs") or [], start=1):
        elements = list(rung.get("elements") or [])
        # Support brief sketch that nests under rails.elements
        if not elements and isinstance(rung.get("rails"), dict):
            elements = list((rung.get("rails") or {}).get("elements") or [])
        rungs.append(
            elements_to_program_rung(
                elements,
                rung_id=str(rung.get("id") or index),
                comment=str(rung.get("comment") or ""),
            )
        )
    meta = ladder.get("meta") if isinstance(ladder.get("meta"), dict) else {}
    answers = dict(meta.get("answers") or {})
    hmi_items = list(meta.get("hmi_items") or [])
    descriptions = {
        str(v.get("name")): clean_note(v.get("description"))
        for v in ladder.get("variables") or []
        if isinstance(v, dict) and v.get("name") and clean_note(v.get("description"))
    }
    out = {
        "answers": answers,
        "rungs": rungs,
        "hmi_items": hmi_items,
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
        "ladder_ir": {
            "format": ladder.get("format", IR_FORMAT),
            "version": ladder.get("version", IR_VERSION),
            "dialect": ladder.get("dialect", IR_DIALECT),
        },
    }
    if descriptions:
        out["tag_descriptions"] = descriptions
    aliases = normalize_tag_aliases(meta.get("tag_aliases") or ladder.get("tag_aliases"))
    if aliases:
        out["tag_aliases"] = aliases
    routines_in = ladder.get("routines") if isinstance(ladder.get("routines"), dict) else {}
    routines_out: dict[str, list] = {}
    for rname, rrungs in (routines_in or {}).items():
        name = normalize_routine_name(rname)
        if not name or name == "Main" or not isinstance(rrungs, list):
            continue
        built = []
        for index, rung in enumerate(rrungs, start=1):
            if not isinstance(rung, dict):
                continue
            elements = list(rung.get("elements") or [])
            built.append(
                elements_to_program_rung(
                    elements,
                    rung_id=str(rung.get("id") or f"{name}_{index}"),
                    comment=str(rung.get("comment") or ""),
                )
            )
        if built:
            routines_out[name] = built
    if routines_out:
        out["routines"] = routines_out
    return out


def normalize_ladder_ir(raw: object) -> dict[str, Any]:
    """Validate/normalize an IR dict; raise ValueError on hard errors."""
    if raw is None:
        return empty_ladder()
    if not isinstance(raw, dict):
        raise ValueError("Ladder IR must be an object.")
    fmt = raw.get("format", IR_FORMAT)
    if fmt not in {IR_FORMAT, "cabinet-studio-ladder", "plcopen-import"}:
        # Still accept if rungs present (imported sibling shapes).
        if "rungs" not in raw:
            raise ValueError(f"Unknown ladder format: {fmt!r}")
    ladder = empty_ladder(project_name=str((raw.get("meta") or {}).get("project") or ""))
    if isinstance(raw.get("meta"), dict):
        ladder["meta"].update({k: v for k, v in raw["meta"].items() if k != "project" or v})
        if raw["meta"].get("project"):
            ladder["meta"]["project"] = str(raw["meta"]["project"])
    ladder["version"] = int(raw.get("version") or IR_VERSION)
    ladder["dialect"] = str(raw.get("dialect") or IR_DIALECT)
    ladder["format"] = IR_FORMAT

    variables = []
    for item in raw.get("variables") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        entry = {
            "name": name,
            "class": str(item.get("class") or "internal"),
            "type": str(item.get("type") or "BOOL"),
            "address": str(item.get("address") or ""),
        }
        if item.get("pt_ms") is not None and str(item.get("type", "")).upper() in {"TON", "TOF", "RTO"}:
            entry["pt_ms"] = int(item["pt_ms"])
        if str(item.get("type", "")).upper() in COUNTER_OWNER_BLOCKS or str(item.get("class") or "").lower() == "counter":
            entry["pv"] = clamp_counter(item.get("pv", item.get("pre", 0)))
        if str(item.get("class") or "").lower() == "numeric" or str(item.get("type") or "").upper() in {
            "INT", "DINT", "REAL", "UINT", "LREAL"
        }:
            if item.get("value") is not None:
                entry["value"] = clamp_numeric(item.get("value"))
            elif item.get("initial") is not None:
                entry["value"] = clamp_numeric(item.get("initial"))
        desc = clean_note(item.get("description") or "")
        if desc:
            entry["description"] = desc
        variables.append(entry)
    ladder["variables"] = variables

    rungs = []
    for index, rung in enumerate(raw.get("rungs") or [], start=1):
        if not isinstance(rung, dict):
            raise ValueError(f"Rung {index} must be an object.")
        elements = list(rung.get("elements") or [])
        if not elements and isinstance(rung.get("rails"), dict):
            elements = list((rung.get("rails") or {}).get("elements") or [])
        clean_els = clean_elements(elements)
        rungs.append(
            {
                "id": str(rung.get("id") or index),
                "comment": str(rung.get("comment") or "").strip(),
                "elements": clean_els,
            }
        )
    ladder["rungs"] = rungs
    routines_in = raw.get("routines") if isinstance(raw.get("routines"), dict) else {}
    routines_out: dict[str, list] = {}
    for rname, rrungs in (routines_in or {}).items():
        name = normalize_routine_name(rname)
        if not name or name == "Main" or not isinstance(rrungs, list):
            continue
        built = []
        for index, rung in enumerate(rrungs, start=1):
            if not isinstance(rung, dict):
                continue
            elements = list(rung.get("elements") or [])
            if not elements and isinstance(rung.get("rails"), dict):
                elements = list((rung.get("rails") or {}).get("elements") or [])
            built.append(
                {
                    "id": str(rung.get("id") or f"{name}_{index}"),
                    "comment": str(rung.get("comment") or "").strip(),
                    "elements": clean_elements(elements),
                }
            )
        if built:
            routines_out[name] = built
    if routines_out:
        ladder["routines"] = routines_out
    aliases = normalize_tag_aliases((raw.get("meta") or {}).get("tag_aliases") if isinstance(raw.get("meta"), dict) else raw.get("tag_aliases"))
    if aliases:
        ladder.setdefault("meta", {})["tag_aliases"] = aliases
    return ladder


def _looks_numeric_literal(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return True
    try:
        if t.lower().startswith("0x"):
            int(t, 16)
            return True
        float(t)
        return True
    except ValueError:
        return False



def normalize_tag_aliases(raw: object) -> dict[str, str]:
    """alias → base tag. Alias must be a simple identifier; base may include a member."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        alias = str(key or "").strip()
        base = str(value or "").strip()
        if not alias or not base or " " in alias or alias == base:
            continue
        if _looks_numeric_literal(alias):
            continue
        out[alias] = base
    return out


def resolve_alias(tag: str, aliases: dict[str, str] | None, *, depth: int = 8) -> str:
    """Follow alias chain to a base tag (members stay on the resolved base)."""
    name = (tag or "").strip()
    if not name or not aliases:
        return name
    base, member = split_member(name)
    seen: set[str] = set()
    cur = base
    for _ in range(max(1, depth)):
        if cur in seen:
            break
        seen.add(cur)
        nxt = (aliases or {}).get(cur)
        if not nxt:
            break
        nxt_base, nxt_member = split_member(str(nxt).strip())
        cur = nxt_base or cur
        if nxt_member and not member:
            member = nxt_member
    return f"{cur}.{member}" if member else cur


def collect_tags(ladder: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """Return (inputs_guess, outputs/coils, all_tags) from IR."""
    coils: set[str] = set()
    contacts: set[str] = set()
    numeric_tags: set[str] = set()

    def note_numeric(token: str) -> None:
        t = (token or "").strip()
        if t and not _looks_numeric_literal(t):
            numeric_tags.add(t)

    def walk(els: list[dict[str, Any]]) -> None:
        for el in els:
            kind = (el.get("kind") or "").lower()
            if kind == "contact":
                tag = (el.get("var") or "").strip()
                if tag:
                    contacts.add(tag)
            elif kind == "coil":
                tag = (el.get("var") or "").strip()
                if tag:
                    coils.add(tag)
            elif kind == "or":
                for branch in el.get("branches") or []:
                    walk(branch)
            elif kind in {"timer", "counter"}:
                tag = (el.get("var") or "").strip()
                if tag:
                    coils.add(tag)
                    fb_names.add(tag)
            elif kind == "oneshot":
                for key in ("var", "output"):
                    tag = (el.get(key) or "").strip()
                    if tag:
                        coils.add(tag)
                        if key == "var":
                            storage_bits.add(tag)
            elif kind == "compare":
                note_numeric(str(el.get("source_a") or ""))
                note_numeric(str(el.get("source_b") or ""))
                note_numeric(str(el.get("source_c") or ""))
            elif kind == "math":
                note_numeric(str(el.get("dest") or ""))
                note_numeric(str(el.get("source_a") or ""))
                note_numeric(str(el.get("source_b") or ""))
                # CPT expression tags collected via expression tokens by callers

    fb_names: set[str] = set()
    storage_bits: set[str] = set()
    for rung in ladder.get("rungs") or []:
        walk(list(rung.get("elements") or []))
    for v in ladder.get("variables") or []:
        cls = str(v.get("class") or "").lower()
        name = str(v.get("name") or "")
        if not name:
            continue
        if cls in {"timer", "counter"}:
            fb_names.add(name)
        if cls == "numeric" or str(v.get("type") or "").upper() in {"INT", "DINT", "REAL", "UINT"}:
            numeric_tags.add(name)
    # Member reads (C1.DN, T1.TT) are driven by the FB instance, never forceable inputs.
    contacts = {
        tag
        for tag in contacts
        if not (split_member(tag)[1] and split_member(tag)[0] in fb_names)
    }

    declared_in = {
        str(v.get("name"))
        for v in ladder.get("variables") or []
        if str(v.get("class") or "").lower() == "input" and v.get("name")
    }
    declared_out = {
        str(v.get("name"))
        for v in ladder.get("variables") or []
        if str(v.get("class") or "").lower() in {"output", "timer", "counter"} and v.get("name")
    }
    declared_in -= storage_bits
    inputs = (contacts - coils - numeric_tags) | declared_in
    outputs = coils | declared_out
    all_tags = contacts | coils | declared_in | declared_out | numeric_tags
    return inputs, outputs, all_tags
