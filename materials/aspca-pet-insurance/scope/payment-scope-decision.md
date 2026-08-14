# Payment-scope decision — aspca-pet-insurance

Decision: **a hash-bound payment-scope proposal is required and is stored in
`scope/payment-scope.json`.**

The clone models a strictly local payment journey so that checkout semantics
can be exercised without collecting or simulating real credentials:

- The only accepted client payment input is one configured opaque sandbox
  scenario id (`sandbox-approved`, `sandbox-declined`, or `sandbox-retry`).
- Amount, currency, owner and canonical fingerprint are computed from the
  persisted quote by the server. Card number, expiry, CVV, bank account,
  Stripe identifiers and client-supplied totals remain forbidden.
- The only adapter is `local-sandbox`; `stripe_test` is absent and live
  payments are forbidden.
- An approved attempt may establish a policy only when approval consumption,
  the enrollment insert and the branded `LOCAL_SIMULATION` mail job commit in
  one site-bound SQLite transaction. Declined and retryable attempts create no
  policy or mail.
- This is a clone-local contract. The source walk did not expose a payment
  surface, so no visual or behavioral claim about the source payment pages is
  made.

Authorization remains `STRIPE_TEST_AUTHORIZED=false` and
`LIVE_PAYMENT_AUTHORIZED=false`; no real mail or payment side effect is in
scope.
