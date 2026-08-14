# Offline-clone context handoff

This contract keeps a long clone run out of any one conversation window. It is
orchestration state only: it is not source evidence, a diagnostic report, an
acceptance decision, or release authority.

## Rollover nodes

Create or replace `materials/<site-id>/scope/agent-handoff.md`:

- after completing one phase reference and before reading the next reference;
- before waiting for human input;
- before a phase worker returns for any other reason; and
- early when repeated large reads, browser results, or tool output make the
  current context expensive.

A phase closer is the only writer; parallel explorers and implementation
workers return bounded summaries and artifact paths to that closer instead of
editing the handoff.

The handoff contains only durable state needed to resume: the current and next
reference, exact authorization boundaries, repository-relative artifact paths,
completed work, open findings, unavailable evidence, next actions, and any
human-owned input still required. All other engineering detail stays in its
original artifact. Keep raw DOM, page text, screenshots, network bodies, raw
tool output, private values, credentials, cookies, tokens, signed URLs, browser
profiles, and session secrets out of it.

Use this compact Markdown shape:

```markdown
# Offline-clone phase handoff

- Site: <site-id>
- Status: continue | human-input-required | blocked | complete
- Current reference: references/0N-name.md
- Next reference: references/0N-name.md | none

## Authorization

<Only explicit source-mutation, email, payment, push, PR, deployment and rights
boundaries needed by the next phase.>

## Completed

<Short list of completed work.>

## Durable paths

<Repository-relative paths the next worker must inspect.>

## Open findings and unavailable evidence

<Only unresolved items.>

## Next actions

<Ordered, bounded actions for the next worker.>

## Human input

<One combined request, or "None".>
```

## Automatic fresh-context continuation

The coordinator keeps orchestration only. At a rollover node it waits for the
current workers, launches one phase closer to consolidate and write the handoff,
then starts the next reference in a new standard subagent with a fresh context.
Use a standard subagent, not a fork that inherits the conversation. Pass paths,
not file bodies:

```text
Execute one WebsiteBench offline-clone phase for materials/<site-id>.
Read AGENTS.md, CLAUDE.md,
prompts/offline-clone/autonomous-source-to-clone.md,
prompts/offline-clone/context-handoff.md,
materials/<site-id>/scope/agent-handoff.md, and only the reference named by the
handoff status: resume the current reference after human input, or enter the
next reference after a completed phase. Work within the recorded authorization.
Before returning, replace the handoff and return only its path, status, next
reference, durable paths, and unresolved findings.
```

This fresh subagent is the automatic context-clear boundary. An Agent cannot
issue the interactive Claude Code `/clear` client command and must never claim
that it did. If standard subagents are unavailable, write the handoff, return
`CONTEXT_ROLLOVER_REQUIRED`, and let the outer runner or human start a clean
session from that file.

When the handoff status is `human-input-required`, ask once for all currently
required human-owned fields and continue independent work. After the reply,
start a fresh worker on the same reference. When status is `complete`, set the
next reference to `none` and do not launch another phase.

## Bounded phase result

The phase closer returns at most twelve short lines. It names the handoff path,
status, next reference, durable paths, and open findings. Raw tool output
remains in its declared artifact file and does not return to the coordinator
conversation.
