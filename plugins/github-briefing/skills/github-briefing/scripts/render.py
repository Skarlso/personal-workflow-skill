#!/usr/bin/env python3
"""Render briefing.json (+ optional notes.json) into a single self-contained page.

collect.py supplies facts; notes.json supplies the model's judgement; this
script only assigns severity, groups items, and fills the template.
"""

import argparse
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".claude", "github-briefing")

# id, title, blurb (blurb states the rule, so the grouping is legible)
GROUPS = [
    ("security", "Security", "advisories and security alerts", "crit"),
    ("overdue", "Ignored too long", "waiting on you past the stale threshold", "crit"),
    ("today", "Needs you today", "you are the blocker, clock started recently", "warn"),
    ("pings", "Pinged you, no reply yet", "someone addressed you and you have not spoken since", "accent"),
    ("answered", "You already replied", "no action unless they came back", "ok"),
    ("ci", "CI and releases", "builds, workflow runs, tags", "none"),
    ("rest", "Happened while you slept", "activity on threads you follow", "none"),
]


def severity(i, stale_days):
    if i.get("bucket") == "security":
        return "crit"
    if i.get("streak", 0) >= 3 or (i.get("waiting_days") or 0) >= stale_days:
        return "crit"
    if i.get("ci") == "FAILURE" and i.get("you_are_author"):
        return "crit"
    if i.get("waiting_on_you"):
        return "warn"
    if i.get("bucket") == "direct" and i.get("answered") is False:
        return "accent"
    if i.get("answered") is True and i.get("you_last_spoke_at"):
        return "ok"
    return "none"


def group_of(i, stale_keys):
    if i.get("bucket") == "security":
        return "security"
    if i["key"] in stale_keys:
        return "overdue"
    if i.get("waiting_on_you"):
        return "today"
    if i.get("bucket") == "direct" and i.get("answered") is False:
        return "pings"
    if i.get("answered") is True and i.get("you_last_spoke_at"):
        return "answered"
    if i.get("bucket") == "ci":
        return "ci"
    return "rest"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefing", default=os.path.join(STATE_DIR, "briefing.json"))
    ap.add_argument("--notes", default=os.path.join(STATE_DIR, "notes.json"))
    ap.add_argument("--out", default=os.path.join(STATE_DIR, "briefing.html"))
    ap.add_argument("--title", default="Maintainer Morning Post")
    ap.add_argument("--stale-days", type=float, default=3.0)
    args = ap.parse_args()

    with open(args.briefing) as f:
        d = json.load(f)
    notes = {}
    if os.path.exists(args.notes):
        with open(args.notes) as f:
            notes = json.load(f)

    stale = set(d.get("stale_keys") or [])
    buckets = dict((g[0], []) for g in GROUPS)
    for i in d["items"]:
        i["severity"] = severity(i, args.stale_days)
        buckets[group_of(i, stale)].append(i["key"])

    d["groups"] = [
        {"id": gid, "title": title, "blurb": blurb, "sev": sev, "keys": buckets[gid]}
        for gid, title, blurb, sev in GROUPS if buckets[gid]
    ]
    d["notes"] = notes
    d["stats"]["unanswered_pings"] = sum(
        1 for i in d["items"] if i.get("bucket") == "direct" and i.get("answered") is False)
    d["stats"]["run_number"] = d.get("run_number", 1)

    since = d["window"]["since"].replace("T", " ").replace("Z", "")
    d["window_label"] = "since %s UTC" % since[:16]

    payload = json.dumps(d, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(HERE, "template.html")) as f:
        html = f.read()
    html = html.replace("__TITLE__", args.title).replace("__DATA__", payload)

    with open(args.out, "w") as f:
        f.write(html)
    print(args.out)
    print("%d threads in %d groups, %.0f KB"
          % (len(d["items"]), len(d["groups"]), os.path.getsize(args.out) / 1024.0))


if __name__ == "__main__":
    main()
