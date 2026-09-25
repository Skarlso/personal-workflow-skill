#!/usr/bin/env python3
"""Collect GitHub notifications and derive a morning-briefing dataset.

Facts only. Judgement (narrative, ordering commentary) is added by the model
afterwards; this script never guesses, it only computes from fetched data.
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", "github-briefing")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")

DEFAULT_CONFIG = {
    "ignore_repos": [],
    "priority_repos": [],
    "extra_bots": [],
    "default_window_hours": 24,
    "stale_days": 3,
    "max_enrich": 70,
}

BOTS = {
    "coderabbitai", "netlify", "dependabot", "github-actions", "codecov",
    "sonarcloud", "sonarqubecloud", "renovate", "allcontributors",
    "cla-assistant", "vercel", "deepsource-autofix", "snyk-bot", "mergify",
    "k8s-ci-robot", "kubernetes-prow-robot", "openshift-ci", "stale",
    "codeclimate", "imgbot", "restyled-io", "gitguardian", "socket-security",
    "claude", "copilot-pull-request-reviewer",
}

# reason -> (bucket, human label, base weight)
REASONS = {
    "review_requested":   ("direct", "Review requested", 70),
    "approval_requested": ("direct", "Approval requested", 75),
    "mention":            ("direct", "You were mentioned", 65),
    "assign":             ("direct", "Assigned to you", 60),
    "author":             ("conversation", "Your thread", 45),
    "comment":            ("conversation", "New comment", 30),
    "state_change":       ("conversation", "State changed", 20),
    "manual":             ("conversation", "You subscribed manually", 25),
    "team_mention":       ("direct", "Your team was mentioned", 40),
    "security_alert":     ("security", "Security alert", 95),
    "ci_activity":        ("ci", "CI activity", 15),
    "subscribed":         ("ambient", "Watching", 5),
}


def run(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("%s failed: %s" % (" ".join(cmd[:3]), p.stderr.strip()[:500]))
    return p.stdout


def gh_json(path, paginate=True):
    cmd = ["gh", "api", path, "--cache", "60s"]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    out = run(cmd)
    data = json.loads(out) if out.strip() else []
    if paginate and data and isinstance(data[0], list):
        flat = []
        for page in data:
            flat.extend(page)
        return flat
    return data


def gh_graphql(query):
    p = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query],
                       capture_output=True, text=True)
    if p.returncode != 0 and not p.stdout.strip():
        raise RuntimeError("graphql failed: " + p.stderr.strip()[:500])
    return json.loads(p.stdout)


def parse_ts(s):
    if not s:
        return None
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def load_json(path, fallback):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, ValueError):
        return fallback


def is_bot(login, extra):
    if not login:
        return True
    low = login.lower()
    return low.endswith("[bot]") or low in BOTS or low in extra


def excerpt(text, limit=220):
    if not text:
        return ""
    clean = " ".join(text.split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def fetch_notifications(since_iso):
    paths = ["/notifications?all=false&per_page=100",
             "/notifications?all=true&per_page=100&since=" + since_iso]
    seen = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for page in pool.map(gh_json, paths):
            for n in page:
                seen[n["id"]] = n
    return list(seen.values())


PR_FIELDS = """
  number title url state isDraft createdAt updatedAt
  author { login }
  labels(first:12){nodes{name color}}
  assignees(first:10){nodes{login}}
  reviewRequests(first:20){nodes{requestedReviewer{__typename ... on User{login} ... on Team{slug}}}}
  reviews(last:30){nodes{author{login} state submittedAt url bodyText}}
  comments(last:25){nodes{author{login} createdAt url bodyText}}
  reviewThreads(last:20){nodes{isResolved comments(last:6){nodes{author{login} createdAt url bodyText}}}}
  commits(last:1){nodes{commit{statusCheckRollup{state}}}}
"""

ISSUE_FIELDS = """
  number title url state createdAt updatedAt
  author { login }
  labels(first:12){nodes{name color}}
  assignees(first:10){nodes{login}}
  comments(last:25){nodes{author{login} createdAt url bodyText}}
"""

DISCUSSION_FIELDS = """
  number title url createdAt updatedAt
  author { login }
  comments(last:25){nodes{author{login} createdAt url bodyText}}
"""


def build_query(chunk):
    parts = []
    for alias, owner, name, number in chunk:
        parts.append("""%s: repository(owner:"%s", name:"%s"){ issueOrPullRequest(number:%d){
      __typename
      ... on PullRequest { %s merged mergedAt }
      ... on Issue { %s }
    } }""" % (alias, owner, name, number, PR_FIELDS, ISSUE_FIELDS))
    return "query {\n" + "\n".join(parts) + "\n}"


def enrich(targets):
    """targets: list of (alias, owner, repo, number). Returns alias -> node."""
    chunks = [targets[i:i + 12] for i in range(0, len(targets), 12)]

    def fetch(chunk):
        try:
            return chunk, gh_graphql(build_query(chunk))
        except (RuntimeError, ValueError) as e:
            print("warn: graphql chunk failed: %s" % e, file=sys.stderr)
            return chunk, None

    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for chunk, res in pool.map(fetch, chunks):
            data = (res or {}).get("data") or {}
            for alias, _, _, _ in chunk:
                repo = data.get(alias)
                if repo and repo.get("issueOrPullRequest"):
                    out[alias] = repo["issueOrPullRequest"]
    return out


# --------------------------------------------------------------------------
# derive
# --------------------------------------------------------------------------

def collect_events(node, viewer, extra_bots):
    """Flatten comments / reviews / inline review threads into one event list."""
    events = []

    def add(kind, author, at, url, body, state=None):
        login = (author or {}).get("login") if isinstance(author, dict) else author
        if not at:
            return
        events.append({
            "kind": kind,
            "by": login,
            "at": at,
            "url": url,
            "excerpt": excerpt(body),
            "state": state,
            "bot": is_bot(login, extra_bots),
            "mentions_you": bool(body) and ("@" + viewer.lower()) in (body or "").lower(),
        })

    for c in (node.get("comments") or {}).get("nodes") or []:
        add("comment", c.get("author"), c.get("createdAt"), c.get("url"), c.get("bodyText"))
    for r in (node.get("reviews") or {}).get("nodes") or []:
        add("review", r.get("author"), r.get("submittedAt"), r.get("url"),
            r.get("bodyText"), r.get("state"))
    for t in (node.get("reviewThreads") or {}).get("nodes") or []:
        for c in (t.get("comments") or {}).get("nodes") or []:
            add("review_comment", c.get("author"), c.get("createdAt"), c.get("url"),
                c.get("bodyText"))
    events.sort(key=lambda e: e["at"])
    return events


def derive(notif, node, viewer, cfg, now):
    extra_bots = set(b.lower() for b in cfg["extra_bots"])
    vlow = viewer.lower()
    reason = notif["reason"]
    bucket, label, weight = REASONS.get(reason, ("conversation", reason, 25))
    subject = notif["subject"]
    repo = notif["repository"]["full_name"]

    item = {
        "id": notif["id"],
        "repo": repo,
        "reason": reason,
        "reason_label": label,
        "bucket": bucket,
        "unread": notif.get("unread", False),
        "notified_at": notif["updated_at"],
        "type": subject["type"],
        "title": subject["title"],
        "url": subject.get("url") or "",
        "signals": [],
        "recent": [],
    }

    if subject["type"] == "RepositoryAdvisory":
        item["bucket"] = "security"
        item["reason_label"] = "Security advisory"
        weight = 95
    if subject["type"] in ("CheckSuite", "WorkflowRun"):
        item["bucket"] = "ci"
        if "fail" in subject["title"].lower():
            item["signals"].append("ci-failed")
            weight = 35

    if node is None:
        num = web = None
        bits = (subject.get("url") or "").rstrip("/").split("/")
        if len(bits) > 2 and bits[-1].isdigit():
            num = int(bits[-1])
            kind = "pull" if bits[-2] == "pulls" else "issues"
            web = "https://github.com/%s/%s/%d" % (repo, kind, num)
        item["key"] = "%s#%d" % (repo, num) if num else "%s:%s" % (repo, subject["title"][:60])
        item["number"] = num
        item["url"] = web or "https://github.com/%s" % repo
        item["enriched"] = False
        item["urgency"] = weight
        item["waiting_on_you"] = False
        item["answered"] = None
        return item
    item["enriched"] = True

    number = node.get("number")
    item["key"] = "%s#%s" % (repo, number)
    item["number"] = number
    item["title"] = node.get("title") or item["title"]
    item["url"] = node.get("url") or item["url"]
    item["type"] = node.get("__typename") or item["type"]
    item["author"] = (node.get("author") or {}).get("login")
    item["created_at"] = node.get("createdAt")
    item["updated_at"] = node.get("updatedAt")
    item["is_draft"] = node.get("isDraft", False)
    item["labels"] = [l["name"] for l in ((node.get("labels") or {}).get("nodes") or [])]
    item["assignees"] = [a["login"] for a in ((node.get("assignees") or {}).get("nodes") or [])]
    item["state"] = "MERGED" if node.get("merged") else node.get("state")

    rollup = None
    for c in ((node.get("commits") or {}).get("nodes") or []):
        rollup = ((c.get("commit") or {}).get("statusCheckRollup") or {}).get("state")
    item["ci"] = rollup

    item["you_are_author"] = (item.get("author") or "").lower() == vlow
    item["you_are_assignee"] = vlow in [a.lower() for a in item["assignees"]]

    pending_reviewers = []
    for rr in ((node.get("reviewRequests") or {}).get("nodes") or []):
        r = rr.get("requestedReviewer") or {}
        pending_reviewers.append((r.get("login") or r.get("slug") or "").lower())
    item["review_requested_of_you"] = vlow in pending_reviewers

    events = collect_events(node, viewer, extra_bots)
    human = [e for e in events if not e["bot"]]
    # A review request / assignment is itself something addressed to you, so it
    # counts as an unanswered event until you speak on the thread.
    if reason in ("review_requested", "approval_requested", "assign") and not item["you_are_author"]:
        kind = "assignment" if reason == "assign" else "review_request"
        human.insert(0, {"kind": kind, "by": item.get("author"), "at": item.get("created_at"),
                         "url": item["url"], "excerpt": "", "state": None, "bot": False,
                         "mentions_you": False, "synthetic": True})
        human.sort(key=lambda e: e["at"] or "")
    yours = [e for e in human if (e["by"] or "").lower() == vlow]
    others = [e for e in human if (e["by"] or "").lower() != vlow]

    item["you_last_spoke_at"] = yours[-1]["at"] if yours else None
    item["your_last_review_state"] = next(
        (e["state"] for e in reversed(yours) if e["kind"] == "review" and e["state"]), None)
    real_others = [e for e in others if not e.get("synthetic")]
    if real_others:
        item["last_activity"] = {"by": real_others[-1]["by"], "at": real_others[-1]["at"],
                                 "kind": real_others[-1]["kind"]}
    item["recent"] = [
        {k: e[k] for k in ("kind", "by", "at", "url", "excerpt", "state", "mentions_you")}
        for e in human[-6:] if not e.get("synthetic")
    ]

    # The clock starts at the oldest thing said to you that you have not
    # answered yet — not at an @mention the thread has already moved past.
    spoke = item["you_last_spoke_at"]
    unanswered = [e for e in others if not spoke or e["at"] > spoke]
    item["answered"] = not unanswered

    ping = None
    if reason in ("mention", "team_mention"):
        ping = next((e for e in reversed(unanswered) if e["mentions_you"]), None)
    if ping is None:
        ping = unanswered[0] if unanswered else None
    if ping is None and others:
        ping = next((e for e in reversed(others) if e["mentions_you"]), others[-1])

    if ping:
        item["ping"] = {"by": ping.get("by"), "at": ping.get("at"),
                        "url": ping.get("url") or item["url"],
                        "excerpt": ping.get("excerpt", ""),
                        "kind": ping.get("kind", "comment")}

    if unanswered:
        item["waiting_since"] = unanswered[0]["at"]
    else:
        item["waiting_since"] = spoke or item.get("created_at")

    open_state = item["state"] == "OPEN"
    waiting = False
    if open_state:
        if item["review_requested_of_you"]:
            waiting = True
        elif item["bucket"] == "direct" and not item["answered"]:
            waiting = True
        elif item["you_are_assignee"] and not item["answered"]:
            waiting = True
    item["waiting_on_you"] = waiting
    if not waiting:
        item["waiting_since"] = None
    elif item["waiting_since"]:
        delta = now - parse_ts(item["waiting_since"])
        item["waiting_days"] = round(delta.total_seconds() / 86400.0, 1)

    # signals
    s = item["signals"]
    if item["review_requested_of_you"]:
        s.append("review-pending")
    if item["answered"] is False and item["bucket"] == "direct":
        s.append("unanswered")
    if item.get("ci") == "FAILURE" and item["you_are_author"]:
        s.append("your-ci-failing")
    if item["is_draft"]:
        s.append("draft")
    if item["state"] == "MERGED":
        s.append("merged")
    elif item["state"] == "CLOSED":
        s.append("closed")
    for lab in item["labels"]:
        if lab.lower() in ("security", "critical", "urgent", "priority/critical",
                           "kind/bug", "release-blocker", "blocker"):
            s.append("label:" + lab)

    # urgency
    score = weight
    if item["review_requested_of_you"]:
        score += 15
    if item["answered"] is False:
        score += 10
    if item.get("waiting_days"):
        score += min(20, item["waiting_days"] * 3)
    if "your-ci-failing" in s:
        score += 15
    if any(x.startswith("label:") for x in s):
        score += 10
    if repo in cfg["priority_repos"]:
        score += 15
    if item["is_draft"] or item["state"] in ("MERGED", "CLOSED"):
        score -= 30
    if item["bucket"] == "ambient":
        score -= 10
    item["urgency"] = int(max(0, min(100, score)))
    return item


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=None,
                    help="lookback window; default = since last briefing (or config default)")
    ap.add_argument("--out", default=os.path.join(STATE_DIR, "briefing.json"))
    ap.add_argument("--no-state", action="store_true", help="do not write state.json")
    ap.add_argument("--full", action="store_true", help="enrich ambient items too")
    ap.add_argument("--repo", action="append", default=[],
                    help="limit to owner/repo (repeatable)")
    args = ap.parse_args()

    if not os.path.isdir(STATE_DIR):
        os.makedirs(STATE_DIR)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_FILE, {}))
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)

    state = load_json(STATE_FILE, {"threads": {}, "last_run": None, "runs": 0})
    now = datetime.now(timezone.utc)

    viewer = run(["gh", "api", "user", "--jq", ".login"]).strip()

    if args.hours:
        since = now - timedelta(hours=args.hours)
        mode = "fixed-%dh" % args.hours
    elif state.get("last_run"):
        since = parse_ts(state["last_run"])
        mode = "since-last-briefing"
        cap = now - timedelta(days=14)
        if since < cap:
            since, mode = cap, "since-last-briefing (capped at 14d)"
    else:
        since = now - timedelta(hours=cfg["default_window_hours"])
        mode = "first-run-%dh" % cfg["default_window_hours"]

    notifs = fetch_notifications(iso(since))
    ignore = set(r.lower() for r in cfg["ignore_repos"])
    notifs = [n for n in notifs if n["repository"]["full_name"].lower() not in ignore]
    if args.repo:
        only = set(r.lower() for r in args.repo)
        notifs = [n for n in notifs if n["repository"]["full_name"].lower() in only]
    notifs.sort(key=lambda n: n["updated_at"], reverse=True)

    # Pick what to enrich: everything actionable, plus ambient if --full.
    targets, alias_map = [], {}
    for idx, n in enumerate(notifs):
        bucket = REASONS.get(n["reason"], ("conversation",))[0]
        if bucket == "ambient" and not args.full:
            continue
        if n["subject"]["type"] not in ("PullRequest", "Issue"):
            continue
        url = n["subject"].get("url") or ""
        bits = url.rstrip("/").split("/")
        if len(bits) < 3 or not bits[-1].isdigit():
            continue
        owner, name = n["repository"]["full_name"].split("/", 1)
        alias = "n%d" % idx
        targets.append((alias, owner, name, int(bits[-1])))
        alias_map[n["id"]] = alias
        if len(targets) >= cfg["max_enrich"]:
            break

    nodes = enrich(targets)

    items = []
    for n in notifs:
        node = nodes.get(alias_map.get(n["id"], ""))
        items.append(derive(n, node, viewer, cfg, now))

    # Collapse duplicate notifications for the same thread, keeping the strongest.
    by_key = {}
    for it in items:
        cur = by_key.get(it["key"])
        if cur is None or it["urgency"] > cur["urgency"]:
            if cur is not None:
                it["also_notified_as"] = sorted(
                    set(cur.get("also_notified_as", []) + [cur["reason_label"]]))
            by_key[it["key"]] = it
        else:
            cur.setdefault("also_notified_as", [])
            if it["reason_label"] not in cur["also_notified_as"]:
                cur["also_notified_as"].append(it["reason_label"])
    items = list(by_key.values())

    # memory: first_seen + consecutive-briefing streak while still waiting
    threads = state.get("threads", {})
    for it in items:
        rec = threads.get(it["key"], {})
        it["first_seen"] = rec.get("first_seen") or it["notified_at"]
        prev_streak = rec.get("streak", 0)
        prev_run = rec.get("last_run")
        if it["waiting_on_you"]:
            it["streak"] = prev_streak + 1 if prev_run != iso(now) else prev_streak
        else:
            it["streak"] = 0
        it["previously_waiting"] = bool(rec.get("waiting"))
        it["is_new"] = rec.get("first_seen") is None
        if it["streak"] >= 3:
            it["signals"].append("ignored-%dx" % it["streak"])
            it["urgency"] = min(100, it["urgency"] + it["streak"] * 2)
        threads[it["key"]] = {
            "first_seen": it["first_seen"],
            "last_run": iso(now),
            "waiting": it["waiting_on_you"],
            "streak": it["streak"],
            "title": it["title"],
            "url": it["url"],
        }

    # prune threads untouched for 60 days
    cutoff = iso(now - timedelta(days=60))
    threads = {k: v for k, v in threads.items() if (v.get("last_run") or "") > cutoff}

    items.sort(key=lambda i: (-i["urgency"], i["notified_at"]), reverse=False)

    stale_days = cfg["stale_days"]
    stale = [i for i in items
             if i["waiting_on_you"] and (i.get("waiting_days", 0) >= stale_days or i["streak"] >= 3)]

    timeline = sorted(items, key=lambda i: i["notified_at"], reverse=True)

    repo_rollup = {}
    for i in items:
        r = repo_rollup.setdefault(i["repo"], {"repo": i["repo"], "count": 0, "waiting": 0})
        r["count"] += 1
        if i["waiting_on_you"]:
            r["waiting"] += 1

    briefing = {
        "generated_at": iso(now),
        "viewer": viewer,
        "window": {"since": iso(since), "mode": mode},
        "stats": {
            "threads": len(items),
            "notifications": len(notifs),
            "unread": sum(1 for i in items if i["unread"]),
            "waiting_on_you": sum(1 for i in items if i["waiting_on_you"]),
            "answered": sum(1 for i in items if i["answered"] is True),
            "stale": len(stale),
            "ci_failures": sum(1 for i in items if "your-ci-failing" in i["signals"]
                               or "ci-failed" in i["signals"]),
            "security": sum(1 for i in items if i["bucket"] == "security"),
            "repos": len(repo_rollup),
            "new_since_last": sum(1 for i in items if i.get("is_new")),
        },
        "items": items,
        "stale_keys": [i["key"] for i in stale],
        "timeline": [i["key"] for i in timeline],
        "repo_rollup": sorted(repo_rollup.values(), key=lambda r: -r["waiting"] or -r["count"]),
        "previous_run": state.get("last_run"),
        "run_number": state.get("runs", 0) + 1,
    }

    with open(args.out, "w") as f:
        json.dump(briefing, f, indent=2)

    if not args.no_state:
        state.update({"threads": threads, "last_run": iso(now),
                      "runs": state.get("runs", 0) + 1, "viewer": viewer})
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    print(args.out)
    print(json.dumps(briefing["stats"], indent=2))


if __name__ == "__main__":
    main()
