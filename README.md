# personal-github-update

Two Claude Code plugins for maintainers drowning in GitHub.

| Plugin | What it does |
|---|---|
| [**github-briefing**](plugins/github-briefing) | A morning briefing across every notification. What is urgent, who pinged you where and whether you answered, what you have been ignoring, and what happened in order. |
| [**explain-pr**](plugins/explain-pr) | An architectural explainer for one pull request. Diagrams, a churn map, every file grouped by theme, and a reading order. For PRs too big to hold in your head. |

Both publish a clickable page as a Claude Code Artifact, and both keep the raw data
out of Claude's context by passing it a compact digest instead.

## Install

```
/plugin marketplace add Skarlso/personal-github-update
/plugin install github-briefing@personal-github-update
/plugin install explain-pr@personal-github-update
```

Install either one on its own; they are independent.

## Requirements

- `gh`, authenticated with the `repo` scope. `gh auth status` should list it.
  The notifications API will not answer without it.
- `python3`. Standard library only, no packages to install.

## What lands on your machine

Both plugins write under `~/.claude/`, never into your repos:

| Path | What |
|---|---|
| `~/.claude/github-briefing/` | state, config, and the generated briefing page |
| `~/.claude/explain-pr/<owner>-<repo>-<n>/` | one directory per PR you explain, including its diff |

`github-briefing` keeps a small `state.json` remembering how many mornings in a row a
thread has gone unanswered. That memory is the point: it is what turns "12 open reviews"
into "you have skipped this one four days running."

Neither plugin ever marks a notification as read, comments, or writes to a repository.
Both are read-only against GitHub.

## A note on the published pages

The pages are Claude Code Artifacts. They are **private to you by default** — nobody sees
one unless you share it from the page's own share menu. Worth knowing before you generate
a briefing, because it contains your notification contents, and before you explain a PR
from a private repository.

If you would rather not publish at all, say "don't publish" and you get the page as a
local HTML file instead.

## Local development

Skip the plugin install and symlink the skills so edits are live with no update step:

```bash
git clone https://github.com/Skarlso/personal-github-update
cd personal-github-update
ln -sfn "$PWD/plugins/github-briefing/skills/github-briefing" ~/.claude/skills/github-briefing
ln -sfn "$PWD/plugins/explain-pr/skills/explain-pr" ~/.claude/skills/explain-pr
```

Script paths in each `SKILL.md` resolve as
`${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/<name>/scripts/...`, which works under a
plugin install and a symlink install alike. Do not use both at once, or the skill loads
twice.

To test the marketplace itself before pushing:

```bash
claude plugin marketplace add .
claude plugin install explain-pr@personal-github-update
# ... then undo
claude plugin uninstall explain-pr@personal-github-update
claude plugin marketplace remove personal-github-update
```

## How they are built

The same split in both: a Python script computes facts, Claude supplies judgement, a
second script renders the page. Nothing in the fetching scripts guesses, and Claude never
reads the 200KB of raw JSON or the full diff.

`explain-pr` lays its diagrams out itself as inline SVG rather than emitting mermaid, so
the page looks identical as a local file and as a published artifact. Every file path,
commit, and quoted comment on that page links back to its source on GitHub, so a wrong
claim lands on a dead anchor instead of quietly reading as true.

## License

MIT. See [LICENSE](LICENSE).
