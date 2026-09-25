#!/usr/bin/env python3
"""Compact structural outline of a fetched PR — the only part that enters context.

pr.diff can be megabytes; read this first, then pull specific files with slice.py.
"""

import argparse
import json
import os
from datetime import datetime, timezone


def parse(s):
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z") if s else None


def ago(iso, now):
    dt = parse(iso)
    if not dt:
        return "?"
    h = (now - dt).total_seconds() / 3600.0
    return "%dh" % round(h) if h < 48 else "%dd" % round(h / 24)


def bar(n, top, width=18):
    if top <= 0:
        return ""
    return "#" * max(1, int(round(width * n / float(top))))


def group_dir(path, depth):
    bits = path.split("/")
    if len(bits) <= 1:
        return "(root)"
    return "/".join(bits[:min(depth, len(bits) - 1)]) + "/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--depth", type=int, default=0,
                    help="directory grouping depth; 0 picks one that actually separates things")
    ap.add_argument("--per-dir", type=int, default=10, help="files listed per directory")
    ap.add_argument("--body", type=int, default=4000)
    args = ap.parse_args()

    with open(os.path.join(args.workdir, "pr.json")) as f:
        d = json.load(f)
    now = datetime.now(timezone.utc)

    print("PR %s#%d  %s%s  by @%s" % (d["repo"], d["number"], d["state"],
                                      " (draft)" if d["draft"] else "", d["author"]))
    print(d["title"])
    print("%s <- %s | %d files +%d/-%d | %d commits | opened %s ago%s"
          % (d["base"], d["head"], d["changed_files"], d["additions"], d["deletions"],
             len(d["commits"]), ago(d["created_at"], now),
             " | merged" if d.get("merged_at") else ""))
    if d["labels"]:
        print("labels: " + ", ".join(d["labels"]))
    print("repo: %s (%s)%s" % (d["repo"], d.get("language") or "?",
                               " - " + d["repo_description"] if d.get("repo_description") else ""))
    print("diff: %s (%.0f KB)" % (d["diff_path"], d["diff_bytes"] / 1024.0))

    print("\n--- DESCRIPTION ---")
    print(d["body"][:args.body].strip() or "(empty)")
    if len(d["body"]) > args.body:
        print("... [description truncated]")

    if d["linked_issues"]:
        print("\n--- LINKED ISSUES ---")
        for i in d["linked_issues"]:
            print("#%d %s  %s" % (i["number"], i["title"], i["url"]))
            if i["body"]:
                print("   " + i["body"][:500].replace("\n", " "))

    print("\n--- COMMITS (%d) ---" % len(d["commits"]))
    for c in d["commits"]:
        print("%s +%-5d -%-5d %s" % (c["sha"], c["add"], c["del"], c["headline"][:88]))

    files = d["files"]

    depth = args.depth
    if not depth:
        # Monorepos bury everything under one prefix; go deeper until the biggest
        # group stops swallowing the PR.
        limit = max(6, int(0.4 * len(files)))
        for depth in range(1, 6):
            sizes = {}
            for f in files:
                k = group_dir(f["path"], depth)
                sizes[k] = sizes.get(k, 0) + 1
            if sizes and max(sizes.values()) <= limit:
                break

    dirs = {}
    for f in files:
        key = group_dir(f["path"], depth)
        g = dirs.setdefault(key, {"files": [], "add": 0, "del": 0})
        g["files"].append(f)
        g["add"] += f["add"]
        g["del"] += f["del"]
    ordered = sorted(dirs.items(), key=lambda kv: -(kv[1]["add"] + kv[1]["del"]))
    top = max((v["add"] + v["del"]) for _, v in ordered) if ordered else 0

    print("\n--- WHERE THE CHANGE LIVES (%d files, grouped at depth %d) ---" % (len(files), depth))
    for name, g in ordered:
        print("%-52s +%-6d -%-5d %2d files %s"
              % (name, g["add"], g["del"], len(g["files"]), bar(g["add"] + g["del"], top)))
        for f in g["files"][:args.per_dir]:
            tags = []
            if f["change"] != "modified":
                tags.append(f["change"][:6].upper())
            if f["generated"]:
                tags.append("gen")
            if f["test"]:
                tags.append("test")
            if f["docs"]:
                tags.append("docs")
            short = f["path"][len(name):] if f["path"].startswith(name) else f["path"]
            print("    %-58s +%-6d -%-5d %s" % (short[:58], f["add"], f["del"], ",".join(tags)))
        if len(g["files"]) > args.per_dir:
            print("    ... %d more files here" % (len(g["files"]) - args.per_dir))

    kinds = {}
    for f in files:
        kinds[f["change"]] = kinds.get(f["change"], 0) + 1
    tests = [f for f in files if f["test"]]
    docs = [f for f in files if f["docs"]]
    gen = [f for f in files if f["generated"]]
    print("\n--- SIGNAL ---")
    print("change kinds: " + ", ".join("%s=%d" % kv for kv in sorted(kinds.items())))
    print("tests: %d files +%d | docs: %d files +%d | generated/vendored: %d files +%d"
          % (len(tests), sum(f["add"] for f in tests),
             len(docs), sum(f["add"] for f in docs),
             len(gen), sum(f["add"] for f in gen)))
    real = [f for f in files if not f["generated"] and not f["test"] and not f["docs"]]
    print("hand-written non-test source: %d files +%d/-%d"
          % (len(real), sum(f["add"] for f in real), sum(f["del"] for f in real)))
    print("read these first (top churn, non-generated):")
    for f in real[:12]:
        print("    %-70s +%-6d -%-5d %s" % (f["path"][:70], f["add"], f["del"], f["change"]))
    if d.get("files_truncated"):
        print("WARNING: file list truncated by the API")

    print("\n--- DISCUSSION (%d reviews, %d comments, %d threads) ---"
          % (len(d["reviews"]), len(d["comments"]), len(d["threads"])))
    for r in d["reviews"][-8:]:
        print("@%-18s %-17s %s ago" % (r["by"], r["state"] or "", ago(r["at"], now)))
        if r["body"]:
            print("   " + r["body"][:300].replace("\n", " "))
    for c in d["comments"][-8:]:
        print("@%-18s %-17s %s ago" % (c["by"], "comment", ago(c["at"], now)))
        print("   " + c["body"][:300].replace("\n", " "))
    unresolved = [t for t in d["threads"] if not t["resolved"]]
    if unresolved:
        print("\nunresolved inline threads (%d):" % len(unresolved))
        for t in unresolved[:12]:
            first = t["comments"][0]
            print("  %s:%s  @%s: %s" % (t["path"], t["line"], first["by"],
                                        first["body"][:180].replace("\n", " ")))


if __name__ == "__main__":
    main()
