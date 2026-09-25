# github-briefing

A morning briefing across every GitHub notification, not one repo.
Answers four questions: what is urgent, who pinged me where and did I answer, what
have I been ignoring, and what happened in order. Ships as a clickable page.

## Install

```
/plugin marketplace add Skarlso/personal-github-update
/plugin install github-briefing@personal-github-update
```

Then `/github-briefing`. Needs `gh` authenticated with `repo` scope — the
notifications API will not answer without it — and `python3`.

## Layout

```
skills/github-briefing/
  SKILL.md              what Claude does with the data
  scripts/collect.py    notifications -> briefing.json (facts)
  scripts/digest.py     briefing.json -> compact text (the only part Claude reads)
  scripts/render.py     briefing.json + notes.json -> briefing.html
  scripts/template.html the page: markup, CSS tokens, client-side filtering
```

Split on purpose: `collect.py` computes, Claude judges, `render.py` presents.
Nothing in `collect.py` guesses, and Claude never sees the 170KB of raw thread data.

## Runtime state

Lives outside this repo, in `~/.claude/github-briefing/`:

| File | What |
|---|---|
| `state.json` | per-thread `first_seen` and the consecutive-briefing streak — the memory behind "you have ignored this 4 mornings running" |
| `config.json` | `ignore_repos`, `priority_repos`, `extra_bots`, `stale_days`, `max_enrich` |
| `briefing.json` | last run's facts |
| `notes.json` | last run's judgement |
| `briefing.html` | the page, republished to a stable Artifact URL |

## Signals worth knowing

- **waiting since** is the oldest thing said to you that you have not answered,
  not the newest comment and not the original @mention. A three-month-old ping on
  a thread that moved last week reports the week, not the quarter.
- A review request or an assignment counts as something addressed to you, so a
  brand new PR with no comments still reads as unanswered.
- Bot comments never count as a human waiting. Add more logins to `extra_bots`.
- Nothing is ever marked as read on GitHub.
