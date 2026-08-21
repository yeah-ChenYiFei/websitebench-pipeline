# Site 33 — human trace coverage audit (2026-08-21)

Every requested journey maps to local routes and bound controls. The
interaction contract (`scope/interaction-controls.json`) binds all 23
traces; `test_interaction_contract.py` verifies every control selector
against its rendered route. Behavior beyond the control graph is
covered by the site test suite (292 tests).

| trace | destination | bound controls | behaviors |
|---|---|---|---|
| trace-001 | /, /updates | header-purchases (navigate→/my-purchases/transactions); updates-preferences-save (durable-state→/updates) | durable-state / navigate |
| trace-002 | /specializations/deep-learning | specialization-paid-checkout (navigate→/checkout/deep-learning) | navigate |
| trace-003 | /browse, /browse/business | business-faq-toggle (client-state→/browse/business); public-browse-category (navigate→/browse/data-science) | client-state / navigate |
| trace-004 | / | header-search (navigate→/search); home-promo-next (client-state→/); home-ai-bestsellers (client-state→/) | client-state / navigate |
| trace-005 | /search | public-course (navigate→/learn/neural-networks-deep-learning) | navigate |
| trace-006 | /search | public-course (navigate→/learn/neural-networks-deep-learning) | navigate |
| trace-007 | /signup | signup-registration (submit→/auth/registration/start) | submit |
| trace-008 | /login | login-submit (submit→/auth/login) | submit |
| trace-009 | /specializations/deep-learning | specialization-enrollment-login (safe-boundary→/login); specialization-free-enrollment (durable-state→/enrollments) | durable-state / safe-boundary |
| trace-010 | /specializations/deep-learning | specialization-paid-checkout (navigate→/checkout/deep-learning) | navigate |
| trace-011 | /learn/neural-networks-deep-learning/home/module/1, /learn/neural-networks-deep-learning/lecture/Cuf2f/welcome, /my-learning | my-learning-course (navigate→/learn/neural-networks-deep-learning/home/welcome); course-objectives-toggle (client-state→/learn/neural-networks-deep-learning/home/module/1); course-weekly-target (durable-state→/learn/neural-networks-deep-learning/weekly-target); lesson-reaction (durable-state→/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome/reaction); lesson-report (durable-state→/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome/report) | client-state / durable-state / navigate |
| trace-012 | /learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning/attempt | assignment-submit (durable-state→/learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning/attempt/submit) | durable-state |
| trace-013 | /learn/neural-networks-deep-learning/home/module/1, /my-learning | my-learning-course (navigate→/learn/neural-networks-deep-learning/home/welcome); course-objectives-toggle (client-state→/learn/neural-networks-deep-learning/home/module/1); course-weekly-target (durable-state→/learn/neural-networks-deep-learning/weekly-target) | client-state / durable-state / navigate |
| trace-014 | /account-settings, /account/preferences | preferences-save (durable-state→/account/preferences); account-settings-save (durable-state→/account-settings) | durable-state |
| trace-015 | / | header-search (navigate→/search) | navigate |
| trace-016 | / | header-login (client-state→/login) | client-state |
| trace-017 | /signup | signup-registration (submit→/auth/registration/start) | submit |
| trace-018 | /account-recovery | password-recovery (safe-boundary→/auth/recovery/start) | safe-boundary |
| trace-019 | / | header-purchases (navigate→/my-purchases/transactions) | navigate |
| trace-020 | /checkout/deep-learning | checkout-submit (submit→/checkout/deep-learning) | submit |
| trace-021 | /, /help | home-faq-toggle (client-state→/); help-feedback (durable-state→/help/feedback); support-guidance (navigate→/about/contact) | client-state / durable-state / navigate |
| trace-022 | /websitebench-nonexistent-route | not-found-recovery (navigate→/browse) | navigate |
| trace-023 | /specializations/deep-learning | specialization-paid-checkout (navigate→/checkout/deep-learning) | navigate |

## Notes

- trace-002 and trace-023 are the same task (Deep Learning enrollment to review); both are bound.
- Authenticated and enrolled surfaces (my-learning, lesson, assignment, orders) are covered by owner-scoped backend tests and browser tests rather than the anonymous generic driver.
- Source payment submission, password-recovery submit, assignment answering on the source, certificates, review submission, cancellation, and messaging remain intentionally unperformed (KNOWN_DIFFERENCES).
