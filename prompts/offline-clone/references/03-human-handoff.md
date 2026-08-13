<!-- Phase 4: human trace acquisition and trajectory recording -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `02-task-brief.md` | Next: `04-scope-and-visual.md`

## Phase 4: adaptive human trace acquisition

> **First read “Authorization inside a logged-in session” and “Autonomous
> decision boundary” in the entry prompt.** This phase describes how to obtain
> authenticated state. Once the user completes login, the Agent autonomously
> explores and captures within authenticated state without requesting approval
> page by page. Every “must request” rule in this phase governs only three
> things: **login itself**, **unauthorized source-site side effects**, and the
> verbatim formal **`human_trace_text`**. It does not constrain automated
> exploration within the authorized boundary.

A human trace is neither a prewritten page list nor a passive fallback after
login fails. The Agent first completes public, read-only reconnaissance and
builds initial page families, roles, core journeys, and uncertainties. It then
selects the smallest set of high-value trace candidates worth requesting from a
human. The Agent decides why capture is necessary and which evidence gaps it
should cover. The human decides and supplies the formal text describing what to
demonstrate.

If the site has authentication, state writes, role differences, or core
interactions that public evidence cannot confirm, `trace_candidates` must not
remain empty. Before implementing the affected candidate slice, the Agent must
proactively request at least one purpose-specific Browserbase Live View trace.
If the site is entirely public, has no role differences, and the Agent can
safely observe the complete core experience, it may omit a meaningless human
trace, but must state the reason in the brief.

### When a trace must be requested proactively

Proactively request a trace whenever any of these conditions applies; do not
merely write “login required” in the plan or final report:

- a P0/P1 page requires login, OTP, MFA, CAPTCHA, or pre-existing account state;
- subscription, permission, organization identity, or another entitlement
  changes the page experience;
- a critical business flow changes source-site state and the Agent is not yet
  authorized to perform it automatically;
- public pages and help documentation cannot establish real fields, interaction
  order, error, success, or recovery semantics;
- an empty state does not represent the primary product experience and a
  populated state is needed;
- two reasonable implementation choices would affect P0/P1 experience and
  read-only evidence cannot resolve the ambiguity; or
- without the trace, the candidate would depend on inference.

Do not permanently mark a surface unavailable merely because no authenticated
state is currently present, and do not first implement the candidate slice from
help documentation.

### The Agent selects candidates; the human supplies text

The Agent neither fixes the number of traces in advance nor writes formal trace
content. Instead, evaluate every evidence gap by:

- importance to the core business purpose;
- uncertainty in current evidence;
- the number of pages, states, and interactions one trace can cover;
- whether only a human can complete it;
- acquisition cost and session lifetime; and
- whether omitting it would make the candidate depend on a guess.

Prioritize high-information traces that unlock several P0/P1 states at once,
such as signing in and reaching a populated dashboard, naturally completing the
primary business goal, showing a typical failure and recovery, entering a
materially different role, or demonstrating a source-specific flow that help
documentation cannot reconstruct. These are selection examples, not a fixed
list and not formal trace text the Agent may supply.

Store the candidate, formal human text, and their binding as distinct objects in
`TASK_BRIEF`; do not have the Agent hard-code the handoff in advance:

```json
{
  "trace_acquisition": {
    "mode": "adaptive",
    "agent_must_initiate": true,
    "text_ownership": "human-only",
    "human_trace_texts": [],
    "trace_candidates": [
      {
        "candidate_id": "tc-001",
        "agent_suggested_scope": "",
        "role": "",
        "why_needed": "",
        "uncertainty_resolved": [],
        "expected_coverage": [],
        "requires_authentication": false,
        "requires_source_mutation": false,
        "evidence_priority": "high",
        "human_trace_text_id": null,
        "text_status": "awaiting-human"
      }
    ],
    "requested_traces": [],
    "completed_traces": [],
    "remaining_material_uncertainties": []
  }
}
```

The Agent may combine several evidence gaps into one candidate or show the human
corresponding inventory task IDs, but must leave `human_trace_text_id` empty
until the human supplies source text or explicitly selects existing text. “Use
<TASK_ID>” is an explicit selection; copy that cell verbatim and record its
`source_ref`. Silence, continued operation, provision of login, or “you
decide” does not confirm text.

After receiving human text, the Agent performs only mechanical processing:
assign a stable ID, verify that it contains no secrets, preserve the UTF-8 source
verbatim, and bind the candidate to that ID. Roles,
preconditions, checkpoints, and safe stopping points derived for recording
belong in `derived_capture_plan`; never write them back into or replace the
human source text.

### Proactively request human-written trace text

After selecting a high-value candidate, if it is not yet bound to human text,
the Agent must pause formal recording for that candidate and proactively ask the
human for text. Present the evidence gap and optional inventory IDs instead of
writing a ready-made trajectory that could masquerade as confirmation. For
example:

```text
I found the following material evidence gaps for <role/state>:

- <gap or surface to observe>
- <pages, states, or Inventory Task IDs it is expected to cover>
- <possible source-site side effects and safe stopping points>

In your own words, please provide the trace text for the journey you want to
demonstrate in Live View. You may instead explicitly select existing Inventory
Task IDs. Describe only the business goal and necessary constraints. Do not
include an account, password, OTP, cookie, real payment information, or private
data.
```

The Agent may explain gaps that a piece of text might not cover, but must not
replace it with an Agent rewrite. If the human supplies only an ambiguous
reference, quote the source and ask the smallest necessary clarification; the
clarification and source together form a new human-confirmed version. **Never
self-confirm or generate missing text “to avoid blocking,” “to keep moving,” or
for any other reason.** Waiting for a human when formal text is missing is one
of the few legitimate pauses in this workflow.

### Prepare before requesting the handoff

After formal trace text is confirmed and before asking the human to take over,
prepare:

- how the handoff channel will be established and its remaining lifetime;
- post-login landing-state detection;
- uncertainties the trace must resolve and the priority capture queue;
- viewport, locale, and timezone;
- output locations for screenshots, DOM, geometry, network, console, and the
  Playwright trace;
- **the trajectory recorder output directory and origin allowlist**, as
  described under “Human trajectory recorder”;
- PII/secret sanitization; and
- a recovery plan for channel failure.

Do not wait until the human logs in to decide what to capture. A login handoff
used solely to establish authenticated state, and explicitly excluded from
formal source coverage, may occur before trace text exists. Recording a
business experience still requires binding human text first.

### Establish the human handoff channel

After formal human text is confirmed and the capture plan is ready, the Agent
must prepare the channel rather than making the user build the capture
environment. Select the channel from the browser-provider parallel-preflight
results; **never** assume a particular provider.

**Default channel: the human's local Chrome plus the trajectory recorder.** The
human uses their everyday browser and the Agent attaches only to observe:

```bash
# Human side: run once
google-chrome --remote-debugging-port=9222

# Agent side
websitebench-browser-trajectory record \
  --cdp-url http://127.0.0.1:9222 \
  --allowed-origin https://<source-origin> \
  --output materials/<site-id>/artifacts/trajectory/<trace-id>
```

This channel does not depend on an interactive provider Live View and therefore
eliminates the most common remote-handoff failure mode. The tradeoff is that the
browser environment differs from the capture environment. Declare that boundary
honestly as described under “Human trajectory recorder” and mark the trajectory
as `environment: human-local`.

**Fallback channel: cloud-browser Live View.** Use it when recording and capture
must share an environment or the human cannot expose a local debugging port.
The Agent creates the session, sets a timeout long enough for login and planned
capture, navigates to the login page, and directly verifies working clicks and
keyboard input before handing it to the human. The recorder may also attach to
the cloud session's CDP endpoint by passing its connect URL to `--cdp-url`.

For either channel, never write a session ID, API response, signed CDP/WebSocket
URL, cookie, authorization header, or storage state to the repository,
trajectory, ordinary logs, or summary. Show the Live View URL exactly once in
the private handoff message for that session. Release any Agent-created session
when finished.

### Flexible human/Agent handoff

Offer two approaches according to the situation; do not require a fixed reply
phrase:

1. The user completes only login, OTP, MFA, or onboarding, after which the Agent
   explores autonomously within the authorized scope.
2. The user naturally demonstrates the confirmed `human_trace_text` using the
   source site as usual while the Agent records passively.

**Cover every human action in one handoff.** Before sending the request, combine
all human-dependent items for this round into one list: login, onboarding,
populated-state construction, every journey to demonstrate, and possible role
switches. Do not request login, return half an hour later for a populated state,
and then return an hour later for another role. This staggered interruption was
a primary source of idle time in the measured prior run.

Briefly state why the handoff is needed, what it is expected to cover, and
whether it changes state. For example:

```text
I have completed public-page reconnaissance, but I still cannot directly
confirm <material uncertainty>.

To reproduce <related P0/P1 experience> accurately, I need one browser handoff.
In this round, please cover all of the following in any order, then tell me the
page where you stopped:

1. Sign in.
2. <State to construct and its exact side effect>.
3. Naturally complete this trace, which you supplied and confirmed:
   <Quote human_trace_text verbatim and show human_trace_text_id>.

To prepare, run `google-chrome --remote-debugging-port=9222` locally. I will
attach only as a passive observer. I will not read credentials, capture network
traffic, or record input values or page text. Credential entry is outside the
formal trace. Do not send a password, OTP, cookie, or another secret in chat.
```

Apart from the login entry point, safety boundary, and necessary goal
description, do not prescribe every click. Natural use prevents the Agent's
expectations from shaping source evidence. For cloud Live View, show its URL
exactly once in the private handoff message and never put it in a file, artifact,
trajectory, summary, or later message. Do not operate the same session while
the human has control.

**Do not idle while waiting.** Immediately after sending the handoff request,
switch to independent work such as anonymous capture, asset closure, gate
scripts, and test scaffolding. Return to close the handoff when the human
finishes.

### Login and sensitive input stay outside the formal trace

Pause or discard the trace chunk while a human enters an email/username,
password, OTP/MFA, CAPTCHA, recovery code, private profile value, or payment
information. After the user reports completion, immediately verify the expected
role, origin, and landing state, then start the formal source trace from a clean
authenticated page. Never read or output form history, password fields,
cookies, or storage. Login traces do not enter evidence.

The same rule binds the trajectory recorder. Its sanitization is hard-coded: it
collapses printable keystrokes, redacts common key and card-number patterns, and
does not read credentials. **That is not permission to keep recording during
credential entry.** Either do not start the recorder for login or discard that
segment in full and record the discard outside `session.json`.

### State construction and source mutation

When a representative journey needs populated state, first explain the required
state, evidence value, and exact side effect, then let the user choose:

- the user completes it naturally in Live View;
- the user explicitly authorizes the Agent to perform the exact listed
  operations; or
- abandon the state and mark the corresponding evidence unavailable.

When the user personally performs a set of operations, that authorizes only the
described operations and does not automatically authorize the Agent to perform
other mutations. Purchases, real payments, messages to third parties,
invitations to real users, and deletion of production data cannot be ordinary
trace requirements.

### Adopted formal trajectories

For every adopted trajectory, preserve at least:

- trace ID, role, and prerequisite state;
- `human_trace_text_id` and verbatim source text;
- a separate `derived_capture_plan`;
- starting and final URLs;
- viewport, locale, and timezone;
- critical interactions and visible results;
- task-relevant pre-action, mid-interaction, failure/success, and post-refresh
  states;
- sanitized DOM, geometry, network, and console evidence;
- screenshot, trace, and asset artifacts; and
- the scope uncertainties it actually resolved.

Let the trajectory goal determine the required detail; do not mechanically
demand every UI state for every trace. Perform only explicitly authorized
mutations and use nonsensitive synthetic values. A recording with no human
source text, or with only Agent-suggested text, cannot
count as formal human trace coverage. At most, it is Agent reconnaissance.

### Request iteratively instead of fixing everything in advance

After every human trace, reassess `remaining_material_uncertainties`:

- once evidence is sufficient to implement and verify the related P0/P1 area,
  do not request a duplicate trace;
- when a materially different role or flow is newly discovered, another round
  may be requested proactively;
- batch related capture in the same valid login session when possible;
- do not repeatedly interrupt the user to reach a numeric target; and
- one role's trace does not cover an unobserved, different role.

For premium or paid roles, request only access the user already has. Do not ask
the user to purchase or subscribe, and do not do so autonomously.

If a session expires, decide autonomously whether to create a new session and
request the shortest possible relogin based on remaining evidence value,
recovery cost, and whether source state persists. Do not retry mechanically or
mark the evidence unavailable after the first expiration. Record unavailable
only after the user confirms they lack access or a reasonable recovery fails.

While waiting for a user, continue anonymous, asset, and public-help research,
but do not implement a P0/P1 candidate slice that would depend on guessing the
missing trajectory.

### Trajectory-completion constraint

Before freezing P0/P1 source scope, satisfy one of these conditions:

1. Obtain the smallest human trace set sufficient to resolve material
   uncertainty, with every formal trace bound to human-written or explicitly
   selected source text; or
2. Explicitly record the surfaces the user cannot provide, the affected scope,
   and their unavailable status.

Do not mark obtainable authenticated evidence unavailable merely because the
Agent did not proactively ask the user. Login without the required business-
experience capture does not cover that experience. Agent-generated candidate
text also does not mean a human provided a trace.

## Human trajectory recorder: the second leg of structural evidence

The repository provides `websitebench-browser-trajectory` under
`src/websitebench/browser_trajectory/`. It attaches to an **already running**
Chrome CDP endpoint, injects passive DOM listeners, and writes a sanitized
structured interaction ledger. It does not launch a browser, own a profile, or
intercept network traffic.

```bash
websitebench-browser-trajectory record \
  --cdp-url http://127.0.0.1:9222 \
  --allowed-origin https://<source-origin> \
  --output materials/<site-id>/artifacts/trajectory/<trace-id>
```

Outputs are `actions.jsonl`, the event ledger; `session.json`, the capture
boundary, privacy contract, and counts; and optional `screenshots/`.

### What it can establish: `recorded-trajectory` as an evidence kind

In the evidence model, a recorded trajectory is `directly-observed` for
**structure and sequence**:

- a stable selector for every activated control:
  `tag / id / name / type / role / className / xpath`;
- event sequence and order:
  `click / input / change / submit / scroll / keydown`;
- the `pageLoad` chain, including real routes, redirects, and history behavior;
  and
- form-submission points and their owning element structure.

This is precisely what the phase 9 interaction ledger requires and what parts
of `core_journeys.steps` otherwise rely on inference. **Prefer it over selectors
and step order inferred from a manual walk.**

### What it cannot establish: hard boundaries with no exceptions

Recorder sanitization is hard-coded and cannot be disabled. It **omits** input
values, element text, and URL query/fragment; collapses printable keys to
`"character"`; does not read credentials; and captures no network traffic.
Therefore:

- **No pixels.** It cannot satisfy a visual contract, checkpoint, or regional
  comparison. Capture the phase 6 three-frame source images separately.
- **No copy.** It captures no button text, validation errors, empty-state
  messages, or field labels. Obtain all of them from a DOM/screenshot capture
  pass.
- **No network evidence.** It says nothing about the phase 10 network-closure
  invariant.
- **No cross-origin iframe events.** Injection into a cross-origin frame fails
  silently and continues at `recorder.py:437-443`. A consent banner, third-party
  payment control, or embedded login form inside such a frame **does not**
  appear in the ledger. Never interpret ledger silence as proof that the
  control does not exist.
- **It is not `human_trace_text`.** It is Agent-observed structure, not text
  written by a human. The ownership rule is unchanged: recorder output may
  **never** populate `human_trace_text`; it is only a `derived_capture_plan`
  attachment and evidence for that trajectory.

### Environment boundary: disclose it accurately

Source-side recording runs in the **human's own Chrome** through
`--remote-debugging-port`. Its IP, locale, timezone, extensions, and profile are
not the capture environment. The visual contract is frozen in the capture
environment, such as a cloud browser or sandbox. They are **not the same
environment**.

Therefore:

- a recorded trajectory may establish routes, redirect chains, selectors, step
  order, form actions, and state transitions;
- it **cannot** establish rendering at any viewport, any copy, or any network
  closure;
- every claim crossing this boundary must be refrozen in the capture
  environment; and
- outside `session.json`, separately record the recording runtime identity,
  including Chrome version, viewport, locale, and timezone. Mark the trajectory
  as `environment: human-local` in coverage and count it separately from
  `environment: capture` evidence.

Do not treat the trajectory as pixel or copy evidence merely because “a human
really clicked it on the real site.”

### Two-sided comparison: diagnostic, not a gate

Record the same trajectory once against the source and once against the local
clone, then compare them with the repository command. **Do not hand-write
normalization logic:**

```bash
websitebench-browser-trajectory diff \
  --source materials/<site-id>/artifacts/trajectory/<trace-id> \
  --candidate materials/<site-id>/artifacts/trajectory/<trace-id>.clone \
  --output materials/<site-id>/artifacts/trajectory/<trace-id>.diff.json
```

It aligns normalized projections and compares only
`(type, url_path, tag, id, name, input_type, role)`. It drops timestamps,
coordinates, scroll positions, throttled `scroll`/`input` events, and origin,
because source and loopback origins can never match. Consecutive duplicate
`pageLoad` events collapse automatically; they are artifacts of per-frame
injection, not site behavior.

`--strict` also compares `class_name` and `xpath`. These differ for styling and
nesting changes that users cannot perceive and impose an excessively strict
offline-clone standard, so strict mode is off by default. Enable it temporarily
only to investigate a specific DOM-structure issue.

Interpret divergence in a fixed order: **first suspect that the two human
demonstrations differ; then suspect a missing clone behavior.**

The command report includes `"authority": "diagnostic"` and deliberately has
**no fail-on-divergence mode**. It exits `0` whether or not it finds differences,
making it structurally impossible to wire in as a gate. Its findings inform the
interaction ledger and candidate repair, but do not satisfy any gate, create
source coverage, or replace phase 10 functional and visual verification. A
clean report **does not** prove candidate fidelity.

### When to record

- **Source side:** record every human handoff by default, excluding login as
  described below. This is the cheapest way to maximize the value of one human
  session.
- **Clone side:** after freezing route/state/viewport and frontend samples, but
  before generating the Harbor contract, record each of the same P0/P1
  trajectories once.
- **Do not record login or sensitive input:** although the recorder collapses
  keystrokes and redacts common key patterns, the formal trajectory starts on a
  clean page after authentication. Stop recording or discard the segment while
  the human enters credentials, an OTP, or payment information.
- `--screenshots` is **disabled** by default. Enable it only on an explicitly
  nonsensitive public surface; never enable it in authenticated state.
