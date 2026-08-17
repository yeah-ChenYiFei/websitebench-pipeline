# Site 33 — known differences and evidence limits

## Evidence boundary

- Public reference screenshots were produced only from anonymous, saved SingleFile pages at `1191 × 979`; their provenance is recorded in `source-evidence/desktop-public-captures.json`.
- Those public captures cover the Chinese home/browse/search/specialization/course presentation, unified auth entry, Help guidance, and a safe 404 recovery. They are anonymous public evidence, not an authenticated source session.
- The authenticated source account, learner dashboard, progress, saved items, history, password-reset submission, and course completion paths were **not directly verified**. No credentials, cookies, tokens, profile, or authenticated source artifact is retained.
- Source login, enrollment completion, recovery submit, and checkout submit were not directly verified and must not be inferred from the clone's working local flows.
- An authenticated checkout display was observed only far enough to record public-facing facts: Deep Learning / DeepLearning.AI, a 7-day trial, `¥196/month` after trial, and `¥0` due today. No source trial, payment, order, or enrollment submission occurred.

## Intentional offline reconstruction

- Accounts, registration verification, inbox, progress, bookmarks, reviews, quiz results, history, cancellation, and checkout are clone-local simulations backed by the generated WebsiteBench runtime. They are not claims about source-side persistence or behavior.
- The clone shows the observed CNY trial facts in the checkout UI. Its generated `local-sandbox` ledger remains frozen to the runtime contract's USD minor-unit currency; it never receives card data or contacts a payment provider.
- The source's anonymous login was captured as a modal overlay. The clone uses a synthetic local course backdrop and no external identity provider.
- The Deep Learning AI overview and the `zzzz-no-match-websitebench` no-match recommendation/recovery behavior are deterministic clone-local search behavior. The public capture establishes search context and filters, but does not verify source AI output or an impossible-query response.
- Help evidence is limited to the public article and recovery guidance in the anonymous capture. The clone's account-aware help and recovery actions do not submit to a source service.

## Visual differences

- Source frames include dynamic state that the clone intentionally does not recreate: cookie-consent banners, chat side panels, restored scroll positions, and source-served promotional photography. The clone uses local CSS illustrations and deterministic content instead.
- The source 404 frame is a simplified English recovery view. The clone keeps its shared Chinese navigation and explicit browse/search recovery links to satisfy the human trace, so this checkpoint is structurally rather than pixel-identical.
- Public screenshots are evidence aids only. They do not establish redistribution rights, legal authorization, or a visual acceptance gate.

## Diagnostics

- Static WebsiteBench diagnostics were complete with no remote references or detected secrets at the latest run.
- Live diagnostics were not completed because the host sandbox denied the local bind with `[Errno 1] Operation not permitted`; this is an environment limitation, not a substitute for manual browser replay.
