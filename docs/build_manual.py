"""Build the self-contained HTML user manual from Cabinet-Studio-User-Manual.md.

Handles only the Markdown subset the manual uses: headings, paragraphs, nested
lists, pipe tables, `> **Kind:**` callouts, bold, inline code and links.
Writes docs/Cabinet-Studio-User-Manual.html and copies it into the app package
(mvp/cabinet_studio/docs/) so the frozen build can open it.

    python docs/build_manual.py
"""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "Cabinet-Studio-User-Manual.md"
OUT = HERE / "Cabinet-Studio-User-Manual.html"
PKG_COPY = HERE.parent / "mvp" / "cabinet_studio" / "docs" / "Cabinet-Studio-User-Manual.html"

CALLOUTS = {"what you'll see": "see", "tip": "tip", "watch out": "warn", "safety": "safety"}
LIST_RE = re.compile(r"^(\s*)(\d+\.|-)\s+(.*)$")

CSS = """
:root { --ink:#1b1b1f; --muted:#555; --accent:#e8711a; --line:#d9d9de; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 19px; line-height: 1.6; color: var(--ink);
       background: #fff; margin: 0; }
main { max-width: 920px; margin: 0 auto; padding: 24px 28px 60px; }
h1 { font-size: 2.2em; margin: .4em 0 .2em; border-bottom: 5px solid var(--accent); padding-bottom: .2em; }
h2 { font-size: 1.6em; margin-top: 2em; padding-top: .3em; border-top: 2px solid var(--line); }
h3 { font-size: 1.25em; margin-top: 1.4em; }
code { font-family: Consolas, monospace; background: #f1f1f4; padding: 1px 5px; border-radius: 4px; font-size: .9em; }
a { color: #1a56c9; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: .92em; }
th, td { border: 1px solid var(--line); padding: 7px 10px; text-align: left; vertical-align: top; }
th { background: #f4f4f7; }
li { margin: .25em 0; }
.callout { border-left: 7px solid; border-radius: 6px; padding: 10px 16px; margin: 1em 0; }
.callout.see { border-color: #2f6bff; background: #eef3ff; }
.callout.tip { border-color: #1e9e57; background: #ebf8f0; }
.callout.warn { border-color: #e0a100; background: #fff7e0; }
.callout.safety { border-color: #c62828; background: #fdecec; }
nav.toc { background: #f7f7fa; border: 1px solid var(--line); border-radius: 8px; padding: 12px 22px; }
nav.toc ol { padding-left: 1.4em; } nav.toc ol ol { font-size: .9em; }
.footer { margin-top: 3em; padding-top: 1em; border-top: 2px solid var(--line); color: var(--muted); font-size: .85em; }
.top { font-size: .8em; }
@media print {
  body { font-size: 12pt; } main { max-width: none; padding: 0; }
  h2 { page-break-before: always; border-top: none; } h2.first { page-break-before: avoid; }
  .callout, table, tr { page-break-inside: avoid; } .top { display: none; } a { color: inherit; text-decoration: none; }
}
"""


def slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)


def render_list(lines: list[str]) -> str:
    """Nested ordered / bullet list from indented lines."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []
    for line in lines:
        m = LIST_RE.match(line)
        if not m:
            out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
            continue
        indent, marker, body = len(m.group(1)), m.group(2), m.group(3)
        tag = "ol" if marker[0].isdigit() else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</{stack.pop()[1]}></li>")
        if not stack or indent > stack[-1][0]:
            if stack:
                out[-1] = out[-1][:-5]
            start = f' start="{marker[:-1]}"' if tag == "ol" and marker != "1." else ""
            out.append(f"<{tag}{start}>")
            stack.append((indent, tag))
        out.append(f"<li>{inline(body)}</li>")
    while stack:
        out.append(f"</{stack.pop()[1]}>" + ("</li>" if stack else ""))
    return "\n".join(out)


def render_table(lines: list[str]) -> str:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    head, body = rows[0], [r for r in rows[2:]]
    out = ["<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"]
    out += ["<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body]
    return "\n".join(out) + "</tbody></table>"


def render_callout(text: str) -> str:
    m = re.match(r"\*\*([^*:]+):\*\*\s*(.*)", text)
    kind = CALLOUTS.get(m.group(1).lower(), "tip") if m else "tip"
    return f'<div class="callout {kind}">{inline(text)}</div>'


def build(md: str) -> tuple[str, int, int]:
    lines = md.splitlines()
    body: list[str] = []
    toc: list[tuple[int, str, str]] = []
    title = "Cabinet Studio User Manual"
    i = 0
    first_h2 = True
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            if level == 1:
                title = text
                body.append(f"<h1>{inline(text)}</h1>")
                body.append("<!--TOC-->")
            else:
                anchor = slug(text)
                toc.append((level, anchor, text))
                cls = ' class="first"' if level == 2 and first_h2 else ""
                first_h2 = first_h2 and level != 2
                top = ' <a class="top" href="#contents">(back to contents)</a>' if level == 2 else ""
                body.append(f'<h{level} id="{anchor}"{cls}>{inline(text)}{top}</h{level}>')
            i += 1
        elif line.startswith(">"):
            body.append(render_callout(line.lstrip("> ").strip()))
            i += 1
        elif line.lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            body.append(render_table(block))
        elif LIST_RE.match(line):
            block = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith((">", "#", "|")):
                if not LIST_RE.match(lines[i]) and not lines[i].startswith(" "):
                    break
                block.append(lines[i])
                i += 1
            body.append(render_list(block))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", ">", "|")) \
                    and not LIST_RE.match(lines[i]):
                para.append(inline(lines[i].strip()))
                i += 1
            body.append("<p>" + "<br>\n".join(para) + "</p>")
    toc_html = ['<nav class="toc" id="contents"><h2 class="first" style="border:none;margin-top:0">Contents</h2><ol>']
    open_sub = False
    for level, anchor, text in toc:
        if level == 2:
            if open_sub:
                toc_html.append("</ol></li>")
                open_sub = False
            elif toc_html[-1].endswith("</a>"):
                toc_html[-1] += "</li>"
            toc_html.append(f'<li><a href="#{anchor}">{inline(text)}</a>')
        elif level == 3:
            if not open_sub:
                toc_html.append("<ol>")
                open_sub = True
            toc_html.append(f'<li><a href="#{anchor}">{inline(text)}</a></li>')
    toc_html.append("</ol></li></ol></nav>" if open_sub else "</li></ol></nav>")
    page = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>\n"
        + "\n".join(body).replace("<!--TOC-->", "\n".join(toc_html))
        + '\n<div class="footer">NOT A CERTIFIED UL 508A DRAWING. Design aid only.</div>'
        "\n</main></body></html>\n"
    )
    sections = sum(1 for lv, _a, _t in toc if lv == 2)
    subsections = sum(1 for lv, _a, _t in toc if lv == 3)
    return page, sections, subsections


def main() -> None:
    page, sections, subsections = build(SRC.read_text(encoding="utf-8"))
    OUT.write_text(page, encoding="utf-8")
    PKG_COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT, PKG_COPY)
    words = len(re.findall(r"\w+", SRC.read_text(encoding="utf-8")))
    print(f"wrote {OUT} and {PKG_COPY}: {sections} sections, {subsections} subsections, ~{words} words")


if __name__ == "__main__":
    main()
