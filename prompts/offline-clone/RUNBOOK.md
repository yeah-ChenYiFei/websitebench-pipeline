# From One URL to an Offline Clone: Human Operator Runbook

This guide is for the **human running the workflow**, not the Agent. The Agent
reads `autonomous-source-to-clone.md` and `references/`.

The essential fact is that only three things require you: logging in, writing
trace source text in your own words, and approving expanded authority. The
Agent handles everything else autonomously. During the previous 68.2-hour
TripIt build, the Agent spent 65% of its time waiting for a human. This workflow
is designed to eliminate that idle time.

---

## 0. Before the run: one-time setup

```bash
# 1. Ensure all entry points are installed. Reinstall after adding a command,
#    or its console script will not exist.
uv pip install -e . --no-deps

# 2. Confirm that the prompts still match the current codebase.
python -m pytest tests/test_prompt_freshness.py -q
```

The second command reports when a prompt still names a command or path that has
been removed. In a fast-moving repository, running it first is cheaper than
letting the Agent hit a nonexistent command halfway through the workflow.

Keep a browser available. During handoff you will use **Chrome on your own
machine**, not a cloud browser.

---

## 1. Start with one instruction

Do not paste the full prompt. Point the Agent to it:

```text
Follow prompts/offline-clone/autonomous-source-to-clone.md.
SOURCE_URL=https://example.com
```

The Agent reads the entry file, about 21 KB of always-resident rules, and loads
`references/0N-*.md` as each phase begins. You do not need to manage load order.

### Eliminate one handoff up front

Trace source text is the only text for which the Agent must stop and ask you.
**Provide it at startup and the Agent never needs a separate pause for it:**

```text
Follow prompts/offline-clone/autonomous-source-to-clone.md.
SOURCE_URL=https://example.com
HUMAN_TRACE_TEXTS=["I want to book a hotel in Seattle for next Wednesday, choose one with free cancellation, and continue to the confirmation page."]
```

This reduces human touchpoints from three to two: startup and login. If you are
unsure what to write, leave it empty. The Agent first finishes read-only
reconnaissance, then asks with concrete evidence gaps, when the trace is easier
to describe.

**Do not provide at this point:** site ID, display name, role list, core
journeys, viewport, timezone, or test data. The Agent derives them from public
evidence. Prefilling them can freeze your guesses into scope.

---

## 2. The Agent works independently; you can leave

In order, with internal concurrency: repository preflight → read-only network
reconnaissance → derive `TASK_BRIEF` → concurrent browser-channel preflight →
anonymous-surface capture.

You have nothing to do during this section. Its outputs are
`materials/<site-id>/scope/derived-task-brief.json` and the first anonymous
screenshots.

**The Agent will not stop here to ask technical questions.** It decides
priorities, oracle shape, capture parameters, and provider selection
autonomously and records the rationale. This is a hard requirement of the entry
prompt's “Autonomous decision boundary.”

---

## 3. Handoff: the only stage that requires your presence

The Agent sends one **combined request** covering everything that needs a human
in the current round: login, states to construct, journeys to demonstrate, and
possible role switches.

### Do three things

**1. Write the trace source text.** In your own words, describe the business
goal you want to demonstrate, for example:

> I want to book a hotel in Seattle for next Wednesday, select one with free
> cancellation, and continue up to the confirmation page.

Rules:

- **You must write it.** The Agent cannot draft, polish, or complete it. It may
  explain evidence gaps, but those are suggestions and cannot masquerade as the
  source text.
- **Do not include an account, password, OTP, cookie, or real payment
  information.** Use synthetic values for any required parameters.

**2. Start Chrome with a debugging port.**

```bash
google-chrome --remote-debugging-port=9222
```

The Agent attaches as a passive observer. It records structure: which element
was activated (`tag/id/name/role/xpath`), event order, and page-load chains. It
**does not read** input values or page text, **does not capture** network
traffic, and **does not touch** credentials. Every printable key collapses to
`"character"`.

**3. Complete the journey naturally.** Log in and perform the trace as you
normally use the site. When finished, tell the Agent only which page you stopped
on.

Do not follow an Agent-authored click-by-click script. Natural operation keeps
the Agent's expectations from shaping the source evidence.

### What you do not need to do

- You do not need to authorize capture page by page. Exploration within
  authenticated state is authorized after login.
- You do not need to stay. Once the Agent acknowledges the handoff, it
  continues and you may leave.

### Important boundaries

| Situation | What to do |
| --- | --- |
| You do not want a category of data accessed | Say “Do not capture payment pages” or “Read-only; do not create anything.” It takes effect immediately. |
| The account contains real sensitive data | Use a test account, or explicitly list pages that must not be captured. |
| Test data created by the Agent needs cleanup | Cleanup is not guaranteed; inspect the account yourself at the end. |
| An action occurs inside a cross-origin iframe | It **cannot be recorded**. Consent banners and third-party payment controls commonly use iframes; do not interpret ledger silence as proof that a control does not exist. |

---

## 4. The Agent works independently again; this is the long section

Scope definition → three-frame visual calibration → asset closure → frontend/
backend implementation → interaction ledger → Harbor contract → diagnostics →
independent blind review.

This was the longest portion of the TripIt run. During it, the Agent:

- works by directory in parallel; `tools/`, `frontend/`, `backend/`, and
  `tests/` are independent;
- repairs findings until the stopping rule applies; and
- records the journey again on the clone, then compares it with the source-side
  recording using `websitebench-browser-trajectory diff`.

### The Agent may contact you once more

It requests another trace only after discovering a **materially different new
role**, such as an administrator view with a substantially different
experience. It does not request duplicate traces for the same role.

---

## 5. At the end, read the report

The report gives neither a completion percentage nor an acceptance conclusion.
It reports coverage by dimension and diagnostic status:

| Diagnostic status | Meaning | How to interpret it |
| --- | --- | --- |
| `clean` | Every declared check completed with no finding | A maintainer still judges the scope, implementation, and evidence together. |
| `findings` | Checks completed and recorded differences | Decide whether the differences affect delivery; CI must not veto automatically. |
| `incomplete` | Input was invalid or a check did not finish | Read the cause and coverage gap before deciding whether to rerun. |

“Indistinguishable under blind review” is a direction, not a machine admission
condition. Delivering a clear gap list is often more valuable than spending ten
hours to gain 0.3% similarity.

The most important part of the report is “Known differences.” It tells you
where the clone can still be distinguished.

---

## 6. Running the result

```bash
# Start the clone locally.
cd materials/<site-id>/clone
WEBSITEBENCH_<SITE>_DATA_DIR=/tmp/<site>-data \
  ../../../.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8451
```

Use the actual port and environment-variable name from that site's
`backend/runtime.json`; they differ by site.

---

## 7. Troubleshooting

| Symptom | Response |
| --- | --- |
| The Agent stops to ask a technical question | Point it to “Autonomous decision boundary,” which requires it to decide. This is a workflow regression worth recording. |
| The Agent repeatedly asks the same thing | Say “Ask everything at once.” Combined questions are a hard prompt requirement. |
| The Agent spends too long on one finding | Say “Apply the stopping rule.” After two rounds without improvement, it must become a known difference. |
| Live View or a browser channel does not work | Do not retry a broken channel indefinitely. Switch after three attempts at the same failure make no progress. |
| The Agent wants to loosen a threshold to turn a metric green | Refuse. Stopping is allowed; lowering the standard is not. The distinction is honesty, not effort. |
| The Agent says a command does not exist | Run the two commands in section 0. |
| The context grows rapidly or auto-compacts repeatedly | Check `materials/<site-id>/scope/agent-handoff.md`. The current phase must close it and the coordinator must start the next reference in a fresh standard subagent. |

---

## Expected time

The TripIt run took 68.2 hours, including 44.4 hours when the Agent was waiting
for a human. The revised expectation is:

- roughly **three human touchpoints**, down from more than a dozen;
- tens of minutes of your active time, concentrated in the handoff; and
- several hours to one day of autonomous Agent time, depending on site
  complexity.

**This is not an unattended daemon that runs forever.** Human-owned login,
trace text, expanded authority and acceptance still require attention. Technical
phase boundaries roll over automatically: the Agent writes
`materials/<site-id>/scope/agent-handoff.md` and starts the next reference in
a fresh standard subagent context. If the installed client cannot create a
standard subagent, it returns `CONTEXT_ROLLOVER_REQUIRED`; start a clean session
and point it at that handoff file.
