# Offline-clone task briefs

These copyable prompts use a configuration-driven machine workflow. The
request supplies source scope, URLs, states, viewports and any usable session;
the Agent may acquire evidence, implement, validate and repair differences
continuously within that scope.

All briefs inherit
[`the real-site source evidence access policy`](../../docs/source-evidence-access-policy.md).
Credentials and session secrets never enter Git or evidence artifacts.

- `RUNBOOK.md`: **start here if you are the human running this.** What you type,
  the three points where you are actually needed, and how to read the result.
- `source-acquisition.md`: bounded source capture.
- `build.md`: implementation and machine-verification loop.
- `autonomous-source-to-clone.md`: derive a complete task brief from one source
  URL, proactively acquire authenticated traces through a human browser
  handoff, then build and verify against the current WebsiteBench workflow.
  This is the always-resident operating contract; the twelve phases live in
  `references/` and are read one at a time.
- `context-handoff.md`: mandatory bounded Markdown state and fresh-context
  rollover at every phase-reference boundary.
- `references/`: per-phase detail for the brief above. The entry prompt's
  operating rules take precedence over anything here.
- `conversation-curation.md`: privacy-conscious extraction of reusable lessons.

These are task briefs, not separate skills or release authority.

`tests/test_prompt_freshness.py` asserts that every command and repository path
these files name still exists, and that the entry index and `references/` agree.
Run it after the repository changes shape.
