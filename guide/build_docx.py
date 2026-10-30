#!/usr/bin/env python3
"""Build the SR-MPLS student lab guide.

Emits three things from the single content source in modules.py:
  1. sr-mpls-training-guide.docx  - the combined book, M0 through M7.
  2. handouts/<id>-<slug>.docx     - one standalone packet per module.
  3. screenshot-index.md           - code-to-description map (screenshot workflow).

Follows the global screenshot workflow: 3-digit codes, snaps/<code>.png, a gray
italic placeholder for any missing code, centered images and captions.

Each module in modules.MODULES is a dict with this schema:
  code        3-digit screenshot code (str)
  id          short id, e.g. "M0"
  title       full heading
  duration    est. time (str)
  objective   one-paragraph goal (str)
  primer      list of concept paragraphs (list[str])
  prereq      lab state required before starting (str)
  build       list of steps: {"step": str, "cmds": list[str], "note": str?}
  verify      list of checks: {"cmd": str, "expect": str (multiline), "read": str}
  screenshot  caption for the module's verification screenshot (str)
  breakfix    student-facing exercise: {"scenario": str, "task": str, "hint": str?}
  brief       list of brief-it-back prompts (list[str])
"""
import os
import re
from docx import Document
from docx.shared import Inches, RGBColor, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from modules import MODULES

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPS = os.path.join(HERE, "snaps")
HANDOUTS = os.path.join(HERE, "handouts")
EXT = (".png", ".jpg", ".jpeg")
MONO = "Consolas"
GRAY = RGBColor(0x88, 0x88, 0x88)
CODE_BG = "F2F2F2"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def snap_for(code):
    for e in EXT:
        p = os.path.join(SNAPS, code + e)
        if os.path.exists(p):
            return p
    return None


def shade(paragraph, fill=CODE_BG):
    """Give a paragraph a light background shading (code-block look)."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)


def add_code_block(doc, lines, prompt=False):
    """Monospace, shaded block. Each line becomes one paragraph run.
    prompt=True renders operational-mode output verbatim (no styling change)."""
    for line in ("\n".join(lines)).splitlines() or [""]:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        shade(p)
        run = p.add_run(line if line else " ")
        run.font.name = MONO
        run.font.size = Pt(9)


def add_label(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    return p


def add_screenshot(doc, code, caption):
    path = snap_for(code)
    if path:
        doc.add_picture(path, width=Inches(6.0))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap = doc.add_paragraph(f"Figure {code}: {caption}")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return True
    p = doc.add_paragraph()
    run = p.add_run(f"[screenshot {code}: {caption}]")
    run.italic = True
    run.font.color.rgb = GRAY
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return False


def render_module(doc, m, heading_level=1):
    """Render one module's full walk-through into an open Document."""
    title = doc.add_heading(m["title"], heading_level)
    if m.get("duration"):
        sub = doc.add_paragraph()
        r = sub.add_run(f"Estimated time: {m['duration']}")
        r.italic = True
        r.font.color.rgb = GRAY

    doc.add_heading("Objective", heading_level + 1)
    doc.add_paragraph(m["objective"])

    if m.get("prereq"):
        p = doc.add_paragraph()
        p.add_run("Before you start: ").bold = True
        p.add_run(m["prereq"])

    doc.add_heading("Concept primer", heading_level + 1)
    for para in m["primer"]:
        doc.add_paragraph(para)

    doc.add_heading("Build steps", heading_level + 1)
    for i, step in enumerate(m["build"], 1):
        p = doc.add_paragraph(style="List Number")
        p.add_run(step["step"]).bold = True
        if step.get("cmds"):
            add_code_block(doc, step["cmds"])
        if step.get("note"):
            note = doc.add_paragraph()
            r = note.add_run("Note: " + step["note"])
            r.italic = True

    doc.add_heading("Verification", heading_level + 1)
    for chk in m["verify"]:
        add_label(doc, chk["cmd"])
        if chk.get("expect"):
            add_code_block(doc, [chk["expect"]])
        if chk.get("read"):
            read = doc.add_paragraph()
            read.add_run("What to look for: ").bold = True
            read.add_run(chk["read"])

    add_screenshot(doc, m["code"], m.get("screenshot", m["title"] + " verification"))

    doc.add_heading("Break / Fix exercise", heading_level + 1)
    bf = m["breakfix"]
    p = doc.add_paragraph()
    p.add_run("Scenario: ").bold = True
    p.add_run(bf["scenario"])
    p = doc.add_paragraph()
    p.add_run("Your task: ").bold = True
    p.add_run(bf["task"])
    if bf.get("hint"):
        hint = doc.add_paragraph()
        r = hint.add_run("Hint: " + bf["hint"])
        r.italic = True
    note = doc.add_paragraph()
    r = note.add_run("The instructor holds the fault-injection and fix commands "
                     "in the answer key. Diagnose it yourself first.")
    r.italic = True
    r.font.color.rgb = GRAY

    doc.add_heading("Brief it back", heading_level + 1)
    doc.add_paragraph("Explain each of these aloud before moving on. If you cannot, "
                      "re-read the primer and re-run the verification commands.")
    for q in m["brief"]:
        doc.add_paragraph(q, style="List Bullet")


def build_combined():
    doc = Document()
    doc.add_heading("SR-MPLS Training Lab (vJunos / GNS3)", 0)
    doc.add_paragraph(
        "Self-paced. Work each module in order; every module builds on the one "
        "before it. Do not skip the Brief it back checkpoints, they are how you "
        "confirm mastery before the next layer. Command examples use PE1 unless "
        "noted; repeat each step on every node using its own values from "
        "configs/stage<N>/<node>.set, or push a whole stage at once with "
        "'python push_lab_configs.py stage<N>-<name>'.")
    doc.add_page_break()
    for m in MODULES:
        render_module(doc, m, heading_level=1)
        doc.add_page_break()
    out = os.path.join(HERE, "sr-mpls-training-guide.docx")
    doc.save(out)
    return out


def build_handouts():
    os.makedirs(HANDOUTS, exist_ok=True)
    paths = []
    for m in MODULES:
        doc = Document()
        doc.add_heading("SR-MPLS Training Lab", 0)
        render_module(doc, m, heading_level=1)
        name = f"{m['id']}-{slug(m['title'].split(None, 1)[-1])}.docx"
        out = os.path.join(HANDOUTS, name)
        doc.save(out)
        paths.append(out)
    return paths


def write_index():
    embedded = sum(1 for m in MODULES if snap_for(m["code"]))
    total = len(MODULES)
    with open(os.path.join(HERE, "screenshot-index.md"), "w") as f:
        f.write("# Screenshot Index\n\n")
        for m in MODULES:
            ok = "✅" if snap_for(m["code"]) else ""
            f.write(f"- {m['code']} {m['id']} {m.get('screenshot', m['title'])} {ok}\n")
        f.write(f"\n{embedded} of {total} screenshots embedded\n")
    return embedded, total


def main():
    combined = build_combined()
    handouts = build_handouts()
    embedded, total = write_index()
    print(f"Wrote {combined}")
    print(f"Wrote {len(handouts)} per-module handouts to {HANDOUTS}/")
    print(f"{embedded}/{total} screenshots embedded.")


if __name__ == "__main__":
    main()
