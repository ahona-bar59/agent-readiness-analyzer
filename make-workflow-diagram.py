"""Render the ARA workflow as a standalone image (workflow.jpg).

A dependency-light diagram generator (Pillow only) so the workflow picture can be
regenerated and dropped into slides / emails for stakeholders.

    pip install Pillow
    python make-workflow-diagram.py
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1880


def _font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITLE = _font(32, True)
F_SUBTITLE = _font(19)
F_NODE = _font(21, True)
F_SUB = _font(18)
F_LBL = _font(17, True)
F_LEG = _font(17)

TEXT = (31, 39, 51)
LINE = (96, 106, 122)

STYLES = {
    "input": ((238, 244, 255), (31, 58, 95)),
    "normal": ((245, 247, 250), (31, 58, 95)),
    "vague": ((255, 243, 221), (154, 106, 0)),
    "decision": ((240, 232, 255), (91, 58, 154)),
    "output": ((233, 240, 249), (31, 58, 95)),
    "terminal": ((228, 244, 233), (10, 125, 51)),
}

# id -> (cx, cy, w, h, lines, style, shape)
NODES = {
    "A": (800, 120, 470, 92, ["Agent README / spec", "detailed OR vague"], "input", "stadium"),
    "B": (800, 250, 470, 92, ["Input Guard", "PII mask · injection block · size cap"], "normal", "box"),
    "C": (800, 380, 470, 92, ["Normalize", "spec · autonomy L1-L4 · summary"], "normal", "box"),
    "D": (800, 512, 470, 92, ["Score 8 Dimensions", "heuristic (offline) or LLM-as-judge"], "normal", "box"),
    "E": (800, 650, 490, 116, ["Hard Gates", "writes · termination · injection",
                               "self-deploy · safety screening"], "normal", "box"),
    "F": (800, 792, 490, 92, ["Input Completeness Assessor", "how much can we actually judge?"], "vague", "box"),
    "G": (800, 922, 490, 92, ["Input Requirements Builder", "required dimensions + parameters"], "vague", "box"),
    "H": (800, 1040, 470, 72, ["Failure Cluster Detector"], "normal", "box"),
    "I": (800, 1185, 360, 150, ["Assessment", "confidence?"], "decision", "diamond"),
    "J": (505, 1370, 400, 92, ["Verdict Engine", "deterministic score + verdict"], "normal", "box"),
    "K": (1095, 1370, 410, 116, ["Verdict Engine", "PROVISIONAL score", "never certified DEPLOYABLE"], "vague", "box"),
    "L": (505, 1565, 400, 92, ["Reports", "JSON · Markdown · HTML"], "output", "box"),
    "M": (1095, 1565, 410, 116, ["Client Requirements Doc", "readme-requirements.md",
                                 "-> send back to client"], "vague", "box"),
    "N": (505, 1745, 500, 116, ["Final Verdict", "DEPLOYABLE / CONDITIONAL /", "NOT_DEPLOYABLE"], "terminal", "stadium"),
}

# (from, to, label)
EDGES = [
    ("A", "B", None), ("B", "C", None), ("C", "D", None), ("D", "E", None),
    ("E", "F", None), ("F", "G", None), ("G", "H", None), ("H", "I", None),
    ("I", "J", "detailed input\nhigh / medium"),
    ("I", "K", "vague input\nlow confidence"),
    ("J", "L", None), ("K", "L", None), ("K", "M", None), ("L", "N", None),
]


def _rect(cx, cy, w, h):
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def _draw_node(d, node):
    cx, cy, w, h, lines, style, shape = node
    fill, outline = STYLES[style]
    x0, y0, x1, y1 = _rect(cx, cy, w, h)
    if shape == "diamond":
        pts = [(cx, y0), (x1, cy), (cx, y1), (x0, cy)]
        d.polygon(pts, fill=fill, outline=outline, width=3)
    elif shape == "stadium":
        d.rounded_rectangle([x0, y0, x1, y1], radius=h / 2, fill=fill, outline=outline, width=3)
    else:
        d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=fill, outline=outline, width=3)

    # Vertically centred text stack: first line is the bold node name.
    heights = [26] + [23] * (len(lines) - 1)
    total = sum(heights) + 3 * (len(lines) - 1)
    ty = cy - total / 2
    for i, ln in enumerate(lines):
        fnt = F_NODE if i == 0 else F_SUB
        tw = d.textlength(ln, font=fnt)
        d.text((cx - tw / 2, ty), ln, font=fnt, fill=TEXT)
        ty += heights[i] + 3


def _arrow(d, p1, p2, label=None):
    x1, y1 = p1
    x2, y2 = p2
    d.line([x1, y1, x2, y2], fill=LINE, width=3)
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 15
    left = (x2 - size * math.cos(ang - 0.5), y2 - size * math.sin(ang - 0.5))
    right = (x2 - size * math.cos(ang + 0.5), y2 - size * math.sin(ang + 0.5))
    d.polygon([(x2, y2), left, right], fill=LINE)
    if label:
        mx, my = x1 + (x2 - x1) * 0.5, y1 + (y2 - y1) * 0.5
        parts = label.split("\n")
        lw = max(d.textlength(p, font=F_LBL) for p in parts)
        lh = 22 * len(parts)
        box = [mx - lw / 2 - 8, my - lh / 2 - 4, mx + lw / 2 + 8, my + lh / 2 + 4]
        d.rounded_rectangle(box, radius=8, fill=(255, 255, 255), outline=(200, 205, 214), width=1)
        ly = my - lh / 2
        for p in parts:
            pw = d.textlength(p, font=F_LBL)
            d.text((mx - pw / 2, ly), p, font=F_LBL, fill=(120, 82, 0))
            ly += 22


def _edge_points(src, dst):
    """From source bottom-centre to destination top-centre (good enough for a
    top-down flow, incl. the branch diagonals)."""
    sx, sy, sw, sh, *_ = src
    dx, dy, dw, dh, *_ = dst
    return (sx, sy + sh / 2), (dx, dy - dh / 2)


def main() -> None:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Title
    title = "Agent Readiness Analyzer (ARA) — Deployment-Readiness Workflow"
    tw = d.textlength(title, font=F_TITLE)
    d.text(((W - tw) / 2, 26), title, font=F_TITLE, fill=(31, 58, 95))
    sub = "Scores any agent README (detailed or vague) and decides deployability"
    sw = d.textlength(sub, font=F_SUBTITLE)
    d.text(((W - sw) / 2, 68), sub, font=F_SUBTITLE, fill=(91, 101, 117))

    # Legend (top-left)
    lx, ly = 40, 40
    d.rounded_rectangle([lx, ly, lx + 26, ly + 20], radius=5,
                        fill=STYLES["vague"][0], outline=STYLES["vague"][1], width=2)
    d.text((lx + 34, ly), "= vague-input handling", font=F_LEG, fill=TEXT)
    d.text((lx, ly + 30), "Verdict = deterministic code", font=F_LEG, fill=(91, 101, 117))
    d.text((lx, ly + 52), "(not an LLM)", font=F_LEG, fill=(91, 101, 117))

    for src, dst, label in EDGES:
        p1, p2 = _edge_points(NODES[src], NODES[dst])
        _arrow(d, p1, p2, label)
    for node in NODES.values():
        _draw_node(d, node)

    img.save("workflow.jpg", "JPEG", quality=92)
    print("Wrote workflow.jpg")


if __name__ == "__main__":
    main()
