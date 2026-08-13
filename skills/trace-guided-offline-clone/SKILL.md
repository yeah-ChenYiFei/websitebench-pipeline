---
name: trace-guided-offline-clone
description: Explicit-only machine-verified workflow using two independent source explorers and one clone writer for a trace-guided offline-clone repair pass. Use only when the user explicitly invokes `$trace-guided-offline-clone`.
---

# Trace-Guided Offline Clone

Run a bounded exploration, repair and machine-verification workflow.

## Prepare

1. Read `docs/source-evidence-access-policy.md` and
   [references/role-contracts.md](references/role-contracts.md) completely.
2. Freeze configured origins, actors, P0/P1 journeys, routes/states/viewports,
   side-effect limits, candidate root and separate artifact roots.
3. Reuse an available authenticated browser session on an approved origin. If
   no usable session is available, mark that surface unavailable and continue.
   Never persist credentials, cookies, tokens, authorization headers, browser
   profiles, payment data or private personal data.

## Execute

1. Launch EA1 and EA2 independently and concurrently when supported. EA1
   explores depth-first; EA2 explores breadth-first. Each writes only its own
   artifact root and neither inspects the candidate. Give them independently
   isolated WebsiteBench/Playwright browser contexts when supported.
2. Use WebsiteBench/Playwright for route/state and text exploration,
   DOM/accessibility inspection, targeted network/console/frame inspection,
   navigation, interaction, screenshots, geometry, assets, trace capture and
   formal evidence.
3. Persist sanitized summaries containing role, action, tool category,
   observable result, truncation state, concise rationale and artifact
   references. Do not record secrets, raw request bodies, sensitive arguments
   or field values, browser profiles or hidden reasoning. Current WebsiteBench
   traces establish visit order and coverage.
4. After both explorations, launch one Clone Agent as the sole candidate writer.
   It builds coverage, repairs differences and runs replay, diff, Harbor and
   release checks. It may repeat bounded repair/check cycles while machine
   evidence identifies actionable differences.
5. While walking the route/state matrix, the Clone Agent records the interaction
   ledger — clone URL, activated selectors, one visible-text and one raw-markup
   rendering proof, and the form action behind each mutation. Once the frontend
   gate passes it derives the Harbor interaction contract from the artifacts the
   build already froze with `websitebench-harbor derive-from-clone
   --clone-manifest materials/<site-dir>/clone.yaml`, resolves every `pending`
   entry from the ledger, replays each profile against the local clone and
   `--promote`s once each artifact reports `assertion_failures: 0`. Use
   `--reconcile` for a hand-authored contract. Derivation and replay are
   diagnostic: they create no trace coverage and satisfy no gate, and
   `opencli-unavailable` leaves the record at `draft` without blocking.

Use current `websitebench-webcloning` and `websitebench-offline-clone`
commands. Historical `clawbench-*` command strings remain data identity only.
Inspect `--help` before constructing invocations and bind validation to the
current checkout.

## Result

Return exact source/clone runtime identities, artifact paths, commands,
coverage, machine decisions, known differences, unavailable evidence,
inferred architecture and changed paths. Zero detected differences means only
that the captured machine evidence found no difference.
`verification_complete` means the current technical gates passed and conveys no legal
or redistribution claim.
