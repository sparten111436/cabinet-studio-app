"""Map interview enclosure brand+size answers onto project physical fields."""

from __future__ import annotations

from cabinet_studio.models.project import Project

# Choice label -> (maker, enclosure_catalog, backplate_catalog, enc_w, enc_h, enc_d, bp_w, bp_h, nema)
_ENCLOSURE_CHOICES: dict[str, tuple[str, str, str, float, float, float, float, float, str]] = {
    "Hoffman 36×30×12 (A363012LP + A36P30)": (
        "Hoffman", "A363012LP", "A36P30", 36, 30, 12, 33, 27, "NEMA 12"
    ),
    "Hoffman 30×24×12 (A302412LP + A30P24)": (
        "Hoffman", "A302412LP", "A30P24", 30, 24, 12, 27, 21, "NEMA 12"
    ),
    "Hoffman 24×24×8 (A242408LP + A24P24)": (
        "Hoffman", "A242408LP", "A24P24", 24, 24, 8, 21, 21, "NEMA 12"
    ),
    "Saginaw 36×30×12 (SCE-36X30X12 + SCE-36P30)": (
        "Saginaw", "SCE-36X30X12", "SCE-36P30", 36, 30, 12, 33, 27, "NEMA 12"
    ),
    "Saginaw 30×24×12 (SCE-30X24X12 + SCE-30P24)": (
        "Saginaw", "SCE-30X24X12", "SCE-30P24", 30, 24, 12, 27, 21, "NEMA 12"
    ),
    "Hammond Eclipse 36×30×12 (EN4SD363012 + EP3630)": (
        "Hammond", "EN4SD363012", "EP3630", 36, 30, 12, 33, 27, "NEMA 12"
    ),
    "Hammond Eclipse 30×24×12 (EN4SD302412 + EP3024)": (
        "Hammond", "EN4SD302412", "EP3024", 30, 24, 12, 27, 21, "NEMA 12"
    ),
}


def parse_enclosure_selection(label: str) -> tuple[str, str, str, float, float, float, float, float, str] | None:
    text = (label or "").strip()
    return _ENCLOSURE_CHOICES.get(text)


def apply_enclosure_selection(project: Project, interview: dict[str, str] | None = None) -> Project:
    """Fill enclosure / backplate inch fields from the interview choice when present."""
    answers = interview if interview is not None else (project.interview or {})
    parsed = parse_enclosure_selection(answers.get("enclosure_selection", ""))
    if parsed is None:
        # Environment washdown hint: keep sizes, bump NEMA language only in interview.
        return project
    maker, enc_cat, bp_cat, ew, eh, ed, bw, bh, nema = parsed
    project.enclosure_maker = maker
    project.enclosure_catalog = f"{enc_cat}+{bp_cat}"
    project.enclosure_width_in = float(ew)
    project.enclosure_height_in = float(eh)
    project.backplate_width_in = float(bw)
    project.backplate_height_in = float(bh)
    if not (answers.get("enclosure_type") or "").strip():
        answers["enclosure_type"] = nema
    # Washdown override from environment
    env = (answers.get("environment") or "").lower()
    if "washdown" in env and "4" not in (answers.get("enclosure_type") or ""):
        answers["enclosure_type"] = "NEMA 4"
    project.interview = dict(answers)
    return project


def sample_hoffman_selection(size: str = "36x30") -> str:
    """Default sample-path Hoffman interview label."""
    if size.startswith("30"):
        return "Hoffman 30×24×12 (A302412LP + A30P24)"
    return "Hoffman 36×30×12 (A363012LP + A36P30)"
