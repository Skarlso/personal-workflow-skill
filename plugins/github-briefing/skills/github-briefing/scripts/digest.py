#!/usr/bin/env python3
"""Print a compact text digest of briefing.json for the model to read.

briefing.json is large; this is the only part that should enter context.
"""

import argparse
import json
import os
from datetime import datetime, timezone

STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "github-briefing")


def parse(s):
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z") if s else None


def ago(iso, now):
    dt = parse(iso)
    if not dt:
        return "?"
    h = (now - dt).total_seconds() / 3600.0
    if h < 1:
        return "%dm" % max(1, int(h * 60))
    if h < 48:
        return "%dh" % round(h)
    return "%dd" % round(h / 24)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefing", default=os.path.join(STATE_DIR, "briefing.json"))
    ap.add_argument("--detail", type=int, default=25, help="how many items get full detail")
    args = ap.parse_args()

    with open(args.briefing) as f:
        d = json.load(f)
    now = parse(d["generated_at"])
    items = d["items"]
    stale = set(d.get("stale_keys") or [])

    print("BRIEFING %s | @%s | run #%s | window %s (%s)"
          % (d["generated_at"], d["viewer"], d.get("run_number"),
             d["window"]["since"], d["window"]["mode"]))
    print("STATS " + " ".join("%s=%s" % (k, v) for k, v in d["stats"].items()))
    print("REPOS " + ", ".join("%s(%d/%dw)" % (r["repo"], r["count"], r["waiting"])
                               for r in d["repo_rollup"][:10]))
    print()

    for n, i in enumerate(items):
        flags = []
        if i["key"] in stale:
            flags.append("OVERDUE")
        if i.get("waiting_on_you"):
            flags.append("waiting-on-you")
        if i.get("answered") is False:
            flags.append("no-reply-from-you")
        elif i.get("you_last_spoke_at"):
            flags.append("you-replied")
        if i.get("streak", 0) >= 2:
            flags.append("surfaced-%dx" % i["streak"])
        if i.get("ci"):
            flags.append("ci=" + i["ci"])
        if i.get("state") and i["state"] != "OPEN":
            flags.append(i["state"].lower())
        if i.get("is_draft"):
            flags.append("draft")
        if i.get("is_new"):
            flags.append("new")

        head = "[%3d] %-58s %s (%s) | %s" % (i["urgency"], i["key"], i["reason_label"],
                                              i.get("bucket", "?"), ", ".join(flags))
        if n >= args.detail:
            print(head + " :: " + i["title"][:80])
            continue

        print(head)
        print("      " + i["title"][:110])
        p = i.get("ping") or {}
        if p.get("by"):
            print("      ping: @%s %s ago%s" % (p["by"], ago(p.get("at"), now),
                                                (' — "%s"' % p["excerpt"][:130]) if p.get("excerpt") else ""))
        if i.get("you_last_spoke_at"):
            print("      you last spoke %s ago%s"
                  % (ago(i["you_last_spoke_at"], now),
                     " (%s)" % i["your_last_review_state"] if i.get("your_last_review_state") else ""))
        elif i.get("enriched"):
            print("      you have never spoken here")
        la = i.get("last_activity") or {}
        if la.get("by"):
            print("      last human activity: @%s %s %s ago" % (la["by"], la["kind"], ago(la["at"], now)))
        extra = []
        if i.get("labels"):
            extra.append("labels: " + ",".join(i["labels"][:5]))
        if i.get("author"):
            extra.append("author: @" + i["author"])
        if extra:
            print("      " + " | ".join(extra))
        print("      " + i["url"])
        print()


if __name__ == "__main__":
    main()
