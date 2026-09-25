---
name: explain-pr
description: Explain a pull request as an architectural overview - what it does, why, how it fits together, where the change lands, and the order to read it in. Builds diagrams and publishes a clickable page. Built for large PRs that are hard to hold in your head. Use when the user says "/explain-pr 1234", "/explain-pr owner/repo#123", pastes a PR URL and asks what it does, or asks to understand a big PR. Examples - "/explain-pr 3636", "/explain-pr https://github.com/kubernetes-sigs/kro/pull/1445", "explain this PR to me".
user_invocable: true
---

# Explain a Pull Request

Produce an architectural explainer for one PR: what it does, why it exists, how the
pieces fit, where the change lands, and a reading order that makes a 4,000-line diff
tractable.

This is an **explainer, not a code review**. Do not assess correctness line by line and
do not recommend merging or not merging. The one exception is the Questions section,
which surfaces design decisions worth a maintainer's attention — scope, trust
boundaries, dependencies, workflow constraints — never style or line-level nits.

## Step 1 — Fetch

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/explain-pr/scripts/fetch.py" <target>
```

`<target>` is `1234`, `owner/repo#1234`, or a PR URL. A bare number only works inside a
git repo. Prints the work directory — call it `$W` for the rest of this run.

## Step 2 — Read the outline

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/explain-pr/scripts/outline.py" $W
```

Read **only** this. It gives you the description, linked issues, commits, the file tree
grouped by churn, which files are tests / docs / generated, and the review discussion.
`$W/pr.diff` is often hundreds of KB and must never be read whole.

Pass `--per-dir 20` if a directory's "… N more files here" is hiding something you need.

## Step 3 — Read the code that matters

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/explain-pr/scripts/slice.py" $W <path-or-substring>... --context 2 --max-lines 250
```

`--context 2` drops unchanged lines more than two lines from a change, which is usually
a 5-10x reduction. `slice.py $W --list` shows every file section and its size.

Read the top hand-written source files from the outline's "read these first" list, plus
anything the PR description or an unresolved review thread points at. Skip generated
files and skim tests. For most PRs this is 5-10 files. Read enough that every claim you
write in step 4 comes from something you actually saw.

## Step 4 — Write explain.json

Write `$W/explain.json`. Prefer a small Python heredoc over shell quoting.

```jsonc
{
  "one_paragraph": "The whole PR. Max 4 sentences. No hedging.",
  "size_verdict": "Is it as big as it looks? Split the line count into tests, docs, generated, and real source. Max 3 sentences.",
  "why": "The problem, the history, the design question it answers. Max 3 paragraphs, max 4 sentences each. Blank lines separate paragraphs; `code` and **bold** work.",

  "diagrams": [{
    "title": "Signing with --tsa",
    "caption": "One sentence stating what the picture shows.",
    "nodes": [{"id": "cli", "label": "ocm sign --tsa", "kind": "changed", "layer": 0, "note": "cli/cmd/sign"}],
    "edges": [{"from": "cli", "to": "req", "label": "before digest", "kind": "new"}]
  }],

  "themes": [{
    "name": "The RFC 3161 client",
    "purpose": "One sentence: what this group of files is for.",
    "detail": "What to notice here. Max 2 paragraphs.",
    "files": [{"path": "exact/path/from/pr.json", "note": "One sentence: what this file does in this PR"}]
  }],

  "reading_order": [{"title": "Read the ADR", "paths": ["docs/adr/0030.md"], "why": "Max 2 sentences: why this file now.", "minutes": 12}],
  "questions": [{"q": "One sentence.", "why": "Max 2 sentences.", "where": "path or area"}],
  "glossary": [{"term": "TSA", "meaning": "One sentence. Narrow domain terms only, never general vocabulary."}]
}
```

### Diagrams

One or two. The first should show the mechanism the PR adds; a second is worth it when
there are two distinct flows (write path and read path, sign and verify, request and
callback). Skip them entirely if the change has no mechanism to draw — a rename sweep
does not need a diagram.

- `layer` is the column, left to right, starting at 0. Layout is automatic: nodes in the
  same layer stack vertically, centred. Keep it to **4 layers and 7 nodes**; past that it
  stops being readable.
- `kind` on a node: `new` (added by this PR, drawn in the accent), `changed` (existing,
  edited here), `existing`, `external` (outside the repo).
- `kind: "new"` on an edge draws it in the accent. Use it for the paths this PR adds.
- **Label every edge** with a verb or the data that moves (`writes`, `verified genTime`,
  `token from descriptor`). Keep labels under ~30 characters; they wrap to two lines and
  anything longer collides with the boxes.
- Draw the mechanism the reader would otherwise have to assemble from prose, not an
  inventory of the subsystem.

### Themes

Cover **every** file in the PR — generated and trivial ones too, in a catch-all theme so
the reader can see they were accounted for. Order themes by what a reader needs first,
not by line count. Use the exact `path` strings from the outline; `render.py` joins them
against the real churn numbers and anything that does not match shows as +0/-0.

Exact paths matter for a second reason: `render.py` turns every matching path into a
link to that file's section of the PR diff, plus a link to the whole file at the head
commit. A misspelled path silently loses both. The same applies to `reading_order[].paths`
and `questions[].where` — give a real file path and it becomes clickable; a directory or
prose stays plain text, which is fine when that is what you mean.

### Reading order

A genuine path through the diff, 5-8 steps. Each step says why *that* file *now* — what
it unlocks for the next step. This is the section they came for, so make it the one you
spend the most thought on. Include a realistic `minutes`.

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

## Step 5 — Render

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude}/skills/explain-pr/scripts/render.py" $W
```

Writes `$W/explain.html`, self-contained, both themes, diagrams as inline SVG. It prints
the diagram count — if it says 0 diagrams, your node ids or edge endpoints did not match.

## Step 6 — Publish

Publish `$W/explain.html` with the **Artifact** tool.

- `favicon`: `🗺️`
- `description`: one sentence naming the PR and what it does

Each PR gets its own file path, so each gets its own URL. Re-running the same PR
redeploys to the same URL only within one conversation — from a new session, pass the
prior `url` if the user wants the same link updated.

Do not load `artifact-design`: the page is prebuilt and you are publishing a file, not
authoring one.

## Step 7 — Report

Under 150 words. The link, then the three or four things they would want to know before
opening it: what it does in one line, whether it is as big as it looks, where to start,
and the sharpest question you found.

## Grounding

Every claim on the page should be one click from its evidence. You never write a URL by
hand — `render.py` builds them from the fetched data — so the job is to name real paths
and real commits and let the renderer link them.

- Never describe a file you did not read. "Generated, skip" is a fine note for one you
  deliberately skipped.
- Every path in `themes` and `reading_order` must exist in the PR.
- If the PR description makes a claim you could not confirm in the diff, attribute it
  ("the description says…") rather than asserting it.
- The glossary uses one test, the one under Voice: would a senior engineer outside this
  subsystem have to search for it. Your own familiarity is not the measure.
