#!/usr/bin/env python3
"""Pull specific files out of a fetched pr.diff, so the whole diff never enters context."""

import argparse
import os
import re
import sys

HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def split_diff(path):
    """Return ordered [(path, [lines])] for each file in the unified diff."""
    out, cur, lines = [], None, []
    with open(path, errors="replace") as f:
        for line in f:
            m = HEADER.match(line.rstrip("\n"))
            if m:
                if cur:
                    out.append((cur, lines))
                cur, lines = m.group(2), [line]
            elif cur:
                lines.append(line)
    if cur:
        out.append((cur, lines))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("paths", nargs="*", help="file paths or substrings to extract")
    ap.add_argument("--list", action="store_true", help="just list file sections and their size")
    ap.add_argument("--max-lines", type=int, default=600, help="cap per file")
    ap.add_argument("--context", type=int, default=0,
                    help="if >0, drop unchanged lines further than N from a change")
    args = ap.parse_args()

    diff = os.path.join(args.workdir, "pr.diff")
    if not os.path.exists(diff):
        raise SystemExit("no pr.diff in " + args.workdir)
    sections = split_diff(diff)

    if args.list or not args.paths:
        print("%d file sections in %s" % (len(sections), diff))
        for p, lines in sections:
            print("%6d lines  %s" % (len(lines), p))
        return

    wanted = []
    for pat in args.paths:
        hits = [s for s in sections if s[0] == pat] or \
               [s for s in sections if pat in s[0]]
        if not hits:
            print("no diff section matching %r" % pat, file=sys.stderr)
        wanted.extend(hits)

    seen = set()
    for p, lines in wanted:
        if p in seen:
            continue
        seen.add(p)
        body = lines
        if args.context > 0:
            keep, marks = [], set()
            for n, l in enumerate(lines):
                if l[:1] in "+-" and not l.startswith(("+++", "---")):
                    for k in range(max(0, n - args.context), min(len(lines), n + args.context + 1)):
                        marks.add(k)
            prev = -2
            for n, l in enumerate(lines):
                if n in marks or l.startswith(("diff --git", "@@", "index ", "new file", "deleted file")):
                    if n > prev + 1:
                        keep.append("   ...\n")
                    keep.append(l)
                    prev = n
            body = keep
        clipped = body[:args.max_lines]
        sys.stdout.write("".join(clipped))
        if len(body) > args.max_lines:
            print("... [%s truncated at %d of %d lines]" % (p, args.max_lines, len(body)))
        print()


if __name__ == "__main__":
    main()
