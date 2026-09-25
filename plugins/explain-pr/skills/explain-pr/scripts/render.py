#!/usr/bin/env python3
"""Turn pr.json + explain.json into a single self-contained explainer page.

Diagrams are laid out here as inline SVG rather than handed to a JS library:
the page must render identically as a local file and as a published artifact.
"""

import argparse
import json
import os
import re
import html
import hashlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

NODE_W = 178
COL_GAP = 124
ROW_GAP = 26
PAD = 28


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def wrap(text, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------
# architecture diagram
# --------------------------------------------------------------------------

def layout_graph(nodes, edges):
    cols = {}
    for n in nodes:
        cols.setdefault(int(n.get("layer", 0)), []).append(n)

    boxes = {}
    for layer in sorted(cols):
        for n in cols[layer]:
            lines = wrap(n["label"], 22)[:3]
            note = wrap(n.get("note", ""), 26)[:2] if n.get("note") else []
            n["_lines"], n["_note"] = lines, note
            n["_h"] = 24 + 17 * len(lines) + (14 * len(note) + 6 if note else 0)

    col_h = {}
    for layer, ns in cols.items():
        col_h[layer] = sum(n["_h"] for n in ns) + ROW_GAP * (len(ns) - 1)
    height = max(col_h.values()) + PAD * 2 if col_h else 120

    for layer in sorted(cols):
        ns = cols[layer]
        y = PAD + (height - PAD * 2 - col_h[layer]) / 2.0
        x = PAD + layer * (NODE_W + COL_GAP)
        for n in ns:
            boxes[n["id"]] = {"x": x, "y": y, "w": NODE_W, "h": n["_h"], "n": n}
            y += n["_h"] + ROW_GAP

    width = PAD * 2 + (max(cols) + 1) * NODE_W + max(cols) * COL_GAP if cols else 400
    return boxes, int(width), int(height)


def svg_graph(diagram, idx):
    nodes, edges = diagram.get("nodes") or [], diagram.get("edges") or []
    if not nodes:
        return ""
    boxes, W, H = layout_graph(nodes, edges)
    mid = "ar%d" % idx
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s" class="graph">'
           % (W, H, esc(diagram.get("caption") or diagram.get("title") or "architecture diagram")),
           '<defs><marker id="%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           'markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>'
           '<marker id="%s-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           'markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker></defs>' % (mid, mid)]

    for e in edges:
        a, b = boxes.get(e.get("from")), boxes.get(e.get("to"))
        if not a or not b:
            continue
        new = e.get("kind") == "new"
        if abs(a["x"] - b["x"]) < 1:
            x1, y1 = a["x"] + a["w"] / 2.0, a["y"] + a["h"]
            x2, y2 = b["x"] + b["w"] / 2.0, b["y"]
            d = "M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
                x1, y1, x1, y1 + 22, x2, y2 - 22, x2, y2)
            lx, ly = (x1 + x2) / 2.0 + 6, (y1 + y2) / 2.0
            anchor = "start"
        else:
            back = b["x"] < a["x"]
            x1 = a["x"] if back else a["x"] + a["w"]
            x2 = b["x"] + b["w"] if back else b["x"]
            y1, y2 = a["y"] + a["h"] / 2.0, b["y"] + b["h"] / 2.0
            dx = (x2 - x1) * 0.45
            d = "M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f" % (
                x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2)
            lx, ly = (x1 + x2) / 2.0, (y1 + y2) / 2.0 - 7
            anchor = "middle"
        out.append('<path d="%s" class="edge%s" marker-end="url(#%s)"/>'
                   % (d, " new" if new else "", mid + ("-a" if new else "")))
        if e.get("label"):
            # Labels sit on top of the path, so they get a plate in the page
            # background colour or the line reads straight through the text.
            ls = wrap(e["label"], 17)[:2]
            tw = max(len(x) for x in ls) * 6.2 + 10
            th = 13 * len(ls) + 4
            bx = lx - (tw / 2.0 if anchor == "middle" else 4)
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" class="eplate"/>'
                       % (bx, ly - th + 3, tw, th))
            ty = ly - th + 14
            for line in ls:
                out.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="elabel%s">%s</text>'
                           % (lx, ty, anchor, " new" if new else "", esc(line)))
                ty += 13

    for nid, b in boxes.items():
        n = b["n"]
        kind = n.get("kind", "existing")
        out.append('<rect x="%.1f" y="%.1f" width="%d" height="%.1f" rx="8" class="node %s"/>'
                   % (b["x"], b["y"], b["w"], b["h"], esc(kind)))
        ty = b["y"] + 21
        for line in n["_lines"]:
            out.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="nlabel %s">%s</text>'
                       % (b["x"] + b["w"] / 2.0, ty, esc(kind), esc(line)))
            ty += 17
        if n["_note"]:
            ty += 2
            for line in n["_note"]:
                out.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="nnote">%s</text>'
                           % (b["x"] + b["w"] / 2.0, ty, esc(line)))
                ty += 14
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------
# change map — deterministic, straight from the file list
# --------------------------------------------------------------------------

def svg_changemap(groups):
    if not groups:
        return ""
    rowh, gap, labelw, barw = 22, 7, 250, 430
    H = PAD * 2 + len(groups) * (rowh + gap)
    W = labelw + barw + 130
    top = max(g["add"] + g["del"] for g in groups) or 1
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Lines changed per area of the '
           'repository, additions and deletions" class="graph map">' % (W, H)]
    y = PAD
    for g in groups:
        aw = barw * g["add"] / float(top)
        dw = barw * g["del"] / float(top)
        out.append('<text x="%d" y="%.1f" text-anchor="end" class="maplabel">%s</text>'
                   % (labelw - 12, y + 15, esc(g["name"][:40])))
        out.append('<rect x="%d" y="%.1f" width="%.1f" height="%d" rx="3" class="badd"/>'
                   % (labelw, y, max(aw, 1.5), rowh - 6))
        if g["del"]:
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%d" rx="3" class="bdel"/>'
                       % (labelw + aw + 2, y, max(dw, 1.5), rowh - 6))
        out.append('<text x="%.1f" y="%.1f" class="mapnum">+%d / -%d &#183; %d files</text>'
                   % (labelw + aw + dw + 12, y + 14, g["add"], g["del"], g["files"]))
        y += rowh + gap
    out.append("</svg>")
    return "".join(out)


def build_groups(files, depth=None):
    def key(p, d):
        bits = p.split("/")
        return "/".join(bits[:min(d, len(bits) - 1)]) + "/" if len(bits) > 1 else "(root)"

    if depth is None:
        limit = max(6, int(0.4 * len(files)))
        for depth in range(1, 6):
            sizes = {}
            for f in files:
                sizes[key(f["path"], depth)] = sizes.get(key(f["path"], depth), 0) + 1
            if sizes and max(sizes.values()) <= limit:
                break
    g = {}
    for f in files:
        k = key(f["path"], depth)
        e = g.setdefault(k, {"name": k, "add": 0, "del": 0, "files": 0})
        e["add"] += f["add"]
        e["del"] += f["del"]
        e["files"] += 1
    return sorted(g.values(), key=lambda e: -(e["add"] + e["del"]))[:14]


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(os.path.join(args.workdir, "pr.json")) as f:
        pr = json.load(f)
    ex_path = os.path.join(args.workdir, "explain.json")
    if not os.path.exists(ex_path):
        raise SystemExit("write explain.json in %s first" % args.workdir)
    with open(ex_path) as f:
        ex = json.load(f)

    # GitHub anchors each file in the PR diff as "diff-" + sha256 of its path.
    # Verified against the rendered files tab: 51/51 paths matched.
    base = "https://github.com/" + pr["repo"]
    by_path = {}
    for f in pr["files"]:
        e = dict(f)
        anchor = hashlib.sha256(f["path"].encode("utf-8")).hexdigest()
        e["diff"] = "%s/pull/%d/files#diff-%s" % (base, pr["number"], anchor)
        if pr.get("head_sha"):
            e["blob"] = "%s/blob/%s/%s" % (base, pr["head_sha"], f["path"])
        by_path[f["path"]] = e
    diagrams = []
    for i, dg in enumerate(ex.get("diagrams") or []):
        svg = svg_graph(dg, i)
        if svg:
            diagrams.append({"title": dg.get("title", ""), "caption": dg.get("caption", ""),
                             "svg": svg})

    payload = {
        "pr": {k: pr[k] for k in ("repo", "number", "title", "url", "state", "draft", "author",
                                  "base", "head", "head_sha", "additions", "deletions", "changed_files",
                                  "labels", "created_at", "merged_at", "language")},
        "commits": pr["commits"],
        "linked_issues": pr["linked_issues"],
        "threads": [t for t in pr["threads"] if not t["resolved"]][:14],
        "stats": {
            "tests": sum(1 for f in pr["files"] if f["test"]),
            "test_lines": sum(f["add"] for f in pr["files"] if f["test"]),
            "docs": sum(1 for f in pr["files"] if f["docs"]),
            "generated": sum(1 for f in pr["files"] if f["generated"]),
            "source": sum(1 for f in pr["files"]
                          if not f["test"] and not f["docs"] and not f["generated"]),
            "commits": len(pr["commits"]),
        },
        "ex": ex,
        "files": by_path,
        "repo_url": base,
        "changemap": svg_changemap(build_groups(pr["files"])),
        "diagrams": diagrams,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    title = "%s #%d explained" % (pr["repo"].split("/")[-1], pr["number"])
    with open(os.path.join(HERE, "template.html")) as f:
        tpl = f.read()
    out = args.out or os.path.join(args.workdir, "explain.html")
    with open(out, "w") as f:
        f.write(tpl.replace("__TITLE__", esc(title))
                   .replace("__DATA__", json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")))

    print(out)
    print("%d diagrams, %d change groups, %.0f KB"
          % (len(diagrams), len(build_groups(pr["files"])), os.path.getsize(out) / 1024.0))


if __name__ == "__main__":
    main()
