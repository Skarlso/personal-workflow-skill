---
name: github-briefing
description: Morning briefing across all of the user's GitHub notifications - what is urgent, who pinged them where and whether they answered, what they have ignored too long, and everything that happened in chronological order. Publishes a clickable page. Use when the user says "/github-briefing", "morning briefing", "what happened on github", "what needs my attention", or asks for their GitHub inbox triaged. Examples - "/github-briefing", "/github-briefing --hours 72", "/github-briefing external-secrets/external-secrets".
user_invocable: true
---

# GitHub Morning Briefing

Cross-repo attention triage for a maintainer. This is **not** code review. Never
assess whether a change is correct or should merge — only who is waiting, how
long, and what the next move is.

The scripts do all the fetching and arithmetic. You supply judgement: a headline,
a lede, and a short reason + next step for the items that matter. Everything you
write must trace to a line in the digest.

## Arguments

| User says | Pass |
|---|---|
| nothing | nothing — window is "since last briefing", 24h on first run |
| "last 3 days", "--hours 72" | `--hours 72` |
| an `owner/repo` | `--repo owner/repo` (repeatable) |
| "don't publish", "just here" | skip step 5 |
| "everything", "include watched repos" | `--full` |

## Step 1 — Collect

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/github-briefing/scripts/collect.py"
```

Writes `~/.claude/github-briefing/briefing.json` and updates
`~/.claude/github-briefing/state.json`. Takes ~10s. It prints the stats block.

Never pass `--no-state` on a real run: state.json is what makes "you have
ignored this 4 mornings running" possible.

This never marks anything as read. Notification state on GitHub is untouched.

## Step 2 — Read the digest

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/github-briefing/scripts/digest.py"
```

Read **only** this. `briefing.json` is ~200KB and must not enter context.

Field meanings, so you do not misread them:

- `OVERDUE` — waiting on you past the stale threshold (default 3 days), or
  surfaced in 3+ consecutive briefings without you acting.
- `waiting-on-you` — a review is still requested of you, or something addressed
  to you is unanswered, on an open thread.
- `no-reply-from-you` — at least one human said something on that thread after
  your last word there. This is the "have I answered?" signal.
- `surfaced-Nx` — this is the Nth briefing in a row it has shown up unresolved.
  Say this out loud when N >= 3; it is the whole point of the memory.
- `ping:` — the oldest unanswered thing addressed to you, with who and when.
  It is deliberately *not* the newest comment.
- `you last spoke ... (CHANGES_REQUESTED)` — your last review verdict, when known.
- Buckets: `direct` (addressed to you), `conversation`, `ci`, `security`,
  `ambient` (just watching).

## Step 3 — Write notes.json

```bash
cat > ~/.claude/github-briefing/notes.json <<'EOF'
{
  "headline": "...",
  "lede": "...",
  "items": {
    "owner/repo#123": {"why": "...", "action": "..."}
  }
}
EOF
```

- `headline` — plain text, max 9 words, the shape of the morning. Lead with
  the number that matters ("Six reviews overdue, one 97 days old"). No HTML.
- `lede` — max 3 sentences. Where attention goes first and why, and the one thing safe
  to skip. Inline `<strong>` is allowed.
- `items` — keyed by the exact `owner/repo#number` from the digest. Cover the
  OVERDUE items and anything else you would genuinely flag, roughly 8-15 entries.
  Do not write a note for every thread; an unremarkable thread with no note
  renders fine.
  - `why` — one sentence. Concrete: who is waiting, since when, what state it is in.
  - `action` — one sentence. The actual next move ("re-review, you left
    CHANGES_REQUESTED and they pushed 21d ago"), a reply they could send, or "close it".

Rules: no invented events. If the digest does not say it, do not write it. Do not
judge the code. Where the right move is to say "this is stale, close it", say so.

## Voice

Readers are senior infrastructure engineers. Assume fluency in Kubernetes, Go, CI,
and distributed systems.

**Never gloss general vocabulary.** CRD, reconciler, operator, admission webhook,
finalizer, informer, RBAC, sidecar, GitOps, controller, DaemonSet, and their like.
If a competent engineer in this ecosystem uses the word weekly, it gets no
explanation.

**Do name the narrow terms this change assumes.** A protocol acronym, an internal
type, a spec section. The test is not "is it obscure" but "would a senior engineer
*outside this subsystem* have to search for it". Yes earns one line. No gets cut.

**One claim per sentence, and no sentence restates the one before it.** The usual
failure is saying the same thing twice at two altitudes.

**Delete on sight:** "it is worth noting", "essentially", "in other words", "this
means that", "as you can see", any opening sentence that restates its own heading,
and any sentence whose removal costs no information.

**Concrete beats categorical.** "the RSA handler", not "the relevant handler".
"97 days", not "a long time". "refuses when another signature exists", not "has
guardrails".

**Terse is about words, not reasons.** Cutting the why is omission, not concision.
"Refuses because the label is signing-relevant" is short and complete at once. When
a length cap forces a choice, drop adjectives and restatement first and the reason
last. The per-field caps are hard limits, not targets to fill.

## Step 4 — Render

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/github-briefing/scripts/render.py"
```

Writes `~/.claude/github-briefing/briefing.html`, self-contained, both themes.
It groups items itself — you do not order anything.

## Step 5 — Publish

Publish with the **Artifact** tool, always with this exact file path so every
morning redeploys to the same URL:

- `file_path`: `~/.claude/github-briefing/briefing.html`
- `favicon`: `☕` (keep it stable)
- `description`: one sentence naming the day's headline number

Do not load `artifact-design` — the page is already designed and you are
publishing a prebuilt file, not authoring one.

## Step 6 — Report in the terminal

Follow the user's output preferences: under 150 words, answer first, no preamble. Give the
artifact link, then at most five lines — the overdue count, the single oldest
unanswered ping with its age, the one thing to do first, and anything genuinely
surprising. Nothing else; the page holds the rest.

## Tuning

`~/.claude/github-briefing/config.json`:

- `ignore_repos` — repos to drop entirely.
- `priority_repos` — +15 urgency.
- `extra_bots` — logins whose comments should not count as a human waiting.
- `stale_days` — default 3.
- `max_enrich` — how many threads get full comment history, default 70.

If the user asks to mute or prioritise a repo, edit this file rather than filtering
by hand at render time.
