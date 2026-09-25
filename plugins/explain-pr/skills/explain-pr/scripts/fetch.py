#!/usr/bin/env python3
"""Fetch everything about one PR into a work directory.

Writes <workdir>/pr.json (metadata, files, commits, discussion) and
<workdir>/pr.diff (the full unified diff). Nothing here interprets the change.
"""

import argparse
import json
import os
import re
import subprocess
import sys

DEFAULT_WORK = os.path.join(os.path.expanduser("~"), ".claude", "explain-pr")

GENERATED = re.compile(
    r"(^|/)(vendor|node_modules|third_party|testdata|\.generated)/"
    r"|(^|/)(go\.sum|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock)$"
    r"|\.(pb|pb\.gw)\.go$|_generated\.go$|\.gen\.go$|zz_generated.*\.go$"
    r"|\.min\.(js|css)$|\.snap$"
)

BOTS = {"coderabbitai", "netlify", "dependabot", "github-actions", "codecov",
        "sonarcloud", "renovate", "cla-assistant", "vercel", "k8s-ci-robot",
        "kubernetes-prow-robot", "claude", "copilot-pull-request-reviewer"}

QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    nameWithOwner
    description
    primaryLanguage { name }
    pullRequest(number:$number) {
      number title url state isDraft merged mergedAt createdAt updatedAt
      headRefOid
      additions deletions changedFiles
      baseRefName headRefName
      bodyText
      author { login }
      labels(first:20){nodes{name}}
      milestone { title }
      closingIssuesReferences(first:10){nodes{number title url bodyText}}
      commits(first:100){nodes{commit{oid messageHeadline messageBody
        author{name user{login}} committedDate additions deletions}}}
      reviews(last:40){nodes{author{login} state submittedAt url bodyText}}
      comments(last:50){nodes{author{login} createdAt url bodyText}}
      reviewThreads(last:60){nodes{isResolved isOutdated path line
        comments(first:8){nodes{author{login} createdAt url bodyText}}}}
    }
  }
}
"""


def sh(cmd, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit("%s failed:\n%s" % (" ".join(cmd[:4]), p.stderr.strip()[:800]))
    return p.stdout


def parse_target(target, cwd_repo):
    """Accept 123, owner/repo#123, or a github PR URL."""
    target = target.strip()
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", target)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = re.match(r"^([^/\s]+)/([^#\s]+)#(\d+)$", target)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = re.match(r"^#?(\d+)$", target)
    if m:
        if not cwd_repo:
            raise SystemExit("bare PR number needs a repo: pass owner/repo#%s" % m.group(1))
        owner, name = cwd_repo.split("/", 1)
        return owner, name, int(m.group(1))
    raise SystemExit("cannot parse PR target: %r" % target)


def clean(text, limit=None):
    if not text:
        return ""
    t = "\n".join(line.rstrip() for line in text.splitlines())
    return t[:limit] if limit else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="123 | owner/repo#123 | PR url")
    ap.add_argument("--workdir", default=DEFAULT_WORK)
    args = ap.parse_args()

    cwd_repo = None
    p = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                       capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        cwd_repo = p.stdout.strip()

    owner, name, number = parse_target(args.target, cwd_repo)
    slug = "%s-%s-%d" % (owner, name, number)
    work = os.path.join(args.workdir, slug)
    if not os.path.isdir(work):
        os.makedirs(work)

    res = json.loads(sh(["gh", "api", "graphql", "-f", "query=" + QUERY,
                         "-F", "owner=" + owner, "-F", "name=" + name,
                         "-F", "number=%d" % number]))
    repo = (res.get("data") or {}).get("repository")
    if not repo or not repo.get("pullRequest"):
        raise SystemExit("PR %s/%s#%d not found" % (owner, name, number))
    pr = repo["pullRequest"]

    diff = sh(["gh", "pr", "diff", str(number), "--repo", "%s/%s" % (owner, name)], check=False)
    diff_path = os.path.join(work, "pr.diff")
    with open(diff_path, "w") as f:
        f.write(diff)

    # REST for files: the GraphQL connection caps at 100, REST paginates to 3000.
    raw_files = json.loads(sh(["gh", "api", "--paginate", "--slurp",
                               "/repos/%s/%s/pulls/%d/files?per_page=100" % (owner, name, number)]))
    flat = []
    for page in raw_files:
        flat.extend(page if isinstance(page, list) else [page])

    files = []
    for n in flat:
        files.append({
            "path": n["filename"],
            "add": n["additions"],
            "del": n["deletions"],
            "change": n["status"],
            "previous": n.get("previous_filename"),
            "generated": bool(GENERATED.search(n["filename"])),
            "test": bool(re.search(r"(^|/)(test|tests|__tests__)/|_test\.|\.test\.|\.spec\.", n["filename"])),
            "docs": bool(re.search(r"\.(md|rst|adoc)$|(^|/)docs?/", n["filename"])),
        })
    files.sort(key=lambda f: -(f["add"] + f["del"]))

    def people(nodes, body_key, time_key):
        out = []
        for n in nodes or []:
            login = (n.get("author") or {}).get("login") or ""
            if login.lower() in BOTS or login.lower().endswith("[bot]"):
                continue
            out.append({"by": login, "at": n.get(time_key), "url": n.get("url"),
                        "state": n.get("state"), "body": clean(n.get(body_key), 1500)})
        return out

    threads = []
    for t in (pr["reviewThreads"]["nodes"] or []):
        cs = people(t["comments"]["nodes"], "bodyText", "createdAt")
        if cs:
            threads.append({"path": t.get("path"), "line": t.get("line"),
                            "resolved": t.get("isResolved"), "outdated": t.get("isOutdated"),
                            "comments": cs})

    out = {
        "repo": repo["nameWithOwner"],
        "repo_description": repo.get("description"),
        "language": (repo.get("primaryLanguage") or {}).get("name"),
        "number": pr["number"], "title": pr["title"], "url": pr["url"],
        "state": "MERGED" if pr["merged"] else pr["state"],
        "draft": pr["isDraft"], "created_at": pr["createdAt"], "merged_at": pr.get("mergedAt"),
        "author": (pr.get("author") or {}).get("login"),
        "base": pr["baseRefName"], "head": pr["headRefName"],
        "head_sha": pr.get("headRefOid"),
        "additions": pr["additions"], "deletions": pr["deletions"],
        "changed_files": pr["changedFiles"],
        "labels": [l["name"] for l in pr["labels"]["nodes"]],
        "milestone": (pr.get("milestone") or {}).get("title"),
        "body": clean(pr.get("bodyText"), 12000),
        "linked_issues": [{"number": i["number"], "title": i["title"], "url": i["url"],
                           "body": clean(i.get("bodyText"), 2500)}
                          for i in pr["closingIssuesReferences"]["nodes"]],
        "commits": [{"sha": c["commit"]["oid"][:10],
                     "headline": c["commit"]["messageHeadline"],
                     "body": clean(c["commit"].get("messageBody"), 600),
                     "by": ((c["commit"].get("author") or {}).get("user") or {}).get("login")
                           or (c["commit"].get("author") or {}).get("name"),
                     "at": c["commit"]["committedDate"],
                     "add": c["commit"]["additions"], "del": c["commit"]["deletions"]}
                    for c in pr["commits"]["nodes"]],
        "files": files,
        "files_truncated": pr["changedFiles"] > len(files),
        "commits_truncated": len(pr["commits"]["nodes"]) >= 100,
        "reviews": people(pr["reviews"]["nodes"], "bodyText", "submittedAt"),
        "comments": people(pr["comments"]["nodes"], "bodyText", "createdAt"),
        "threads": threads,
        "diff_path": diff_path,
        "diff_bytes": len(diff),
        "workdir": work,
    }

    with open(os.path.join(work, "pr.json"), "w") as f:
        json.dump(out, f, indent=2)

    print(work)
    print("%s#%d  %s" % (out["repo"], out["number"], out["title"]))
    print("%d files, +%d/-%d, %d commits, diff %.0f KB"
          % (out["changed_files"], out["additions"], out["deletions"],
             len(out["commits"]), out["diff_bytes"] / 1024.0))
    if out["files_truncated"]:
        print("note: only the first %d files were returned by the API" % len(files),
              file=sys.stderr)


if __name__ == "__main__":
    main()
