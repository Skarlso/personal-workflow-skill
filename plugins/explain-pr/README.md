# explain-pr

`/explain-pr 3636`, `/explain-pr owner/repo#123`, or a PR URL. Produces a page with a
one-paragraph summary, a size verdict that separates real source from tests and
generated files, hand-laid-out architecture diagrams, a churn map, every changed file
grouped into themes, a reading order, questions worth asking, and a glossary of the
terms the PR assumes.

## Install

```
/plugin marketplace add Skarlso/personal-github-update
/plugin install explain-pr@personal-github-update
```

Then `/explain-pr 1234`, `/explain-pr owner/repo#123`, or paste a PR URL.
Needs `gh` authenticated with `repo` scope and `python3`.

## Layout

```
skills/explain-pr/
  SKILL.md              how Claude reads the PR and what it writes
  scripts/fetch.py      PR -> pr.json + pr.diff in ~/.claude/explain-pr/<slug>/
  scripts/outline.py    pr.json -> compact outline (the only part Claude reads)
  scripts/slice.py      pull single files out of pr.diff, optionally context-trimmed
  scripts/render.py     pr.json + explain.json -> explain.html, diagrams included
  scripts/template.html the page
```

`render.py` lays diagrams out itself as inline SVG rather than emitting mermaid, so the
page looks the same as a local file and as a published artifact. Claude supplies nodes
with a `layer` number and labelled edges; columns, spacing, curves, and label plates are
computed. Diff never enters context whole: `outline.py` is ~200 lines and `slice.py
--context 2` trims the rest.
