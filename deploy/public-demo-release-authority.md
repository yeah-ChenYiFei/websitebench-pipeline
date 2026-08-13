# Protected public-demo deployment authority — historical record

> The entries below preserve prior supervised authorization statements. They
> do not authorize a current deployment, do not select a site, and do not
> replace a current scoped user request. Current protected-demo publication is
> available only through the fixed `deploy-<site>-public.yml` dispatcher for
> the selected site; see [`DEPLOYMENT.md`](../DEPLOYMENT.md).

Recorded at: `2026-07-29T23:00:00-04:00`

The user explicitly confirmed authorization to deploy the current local WIP
for these eleven Basic-Auth-protected review domains:

- `amazon.website-bench.com`
- `capterra.website-bench.com`
- `taskrabbit.website-bench.com`
- `petfinder.website-bench.com`
- `edx.website-bench.com`
- `etsy.website-bench.com`
- `eventbrite.website-bench.com`
- `imdb.website-bench.com`
- `change.website-bench.com`
- `workable.website-bench.com`
- `ubereats.website-bench.com`

The same confirmation states that the Amazon Resend sending domain has the
required SPF, DKIM, and DMARC configuration. It authorizes this protected-demo
deployment only. It does not accept R1–R4, clear Harbor or benchmark release
gates, or make any site technically-verified.

## Amazon Stripe test external-effect authorization

Recorded at: `2026-07-31T07:58:26Z`

Human supervisor: GitHub account `reacher-z` (the deployment workspace's SSH
identity). In the current supervised conversation, the supervisor explicitly
requested that the current Amazon Stripe test implementation be redeployed and
stated that they will perform the browser acceptance. This authorization is
limited to the Basic-Auth-protected Stripe sandbox profile and the exact
candidate produced from the current supervised worktree.

Stripe external-effect approval: accepted

Stripe payment mode: test-only

Stripe live mode: forbidden

This record does not authorize real cards, live funds, real fulfillment, public
redistribution of unresolved Amazon assets, or a technically-verified claim. The
post-deploy Worker/build identity, Stripe sandbox Session/event IDs and human
acceptance remain pending until the deployment and browser inspection occur.

At `2026-07-31T12:48:54Z`, the human supervisor confirmed that
`STRIPE_TEST_SECRET_KEY` and `STRIPE_TEST_WEBHOOK_SECRET` had been configured
for the protected Amazon deployment environment. This records only the secret
names and the supervisor's confirmation; no secret value is stored here.

## Workable and Uber Eats protected-demo routing

Recorded at: `2026-08-05T14:03:55Z`

The user requested that Workable and Uber Eats be deployed through the existing
WcodeW WebsiteBench Cloudflare Worker/Container/custom-domain workflow, with
mail verification routed through the existing Redis + Resend Worker boundary.
The request explicitly excludes VPS, Apache, nginx, systemd, certbot, local
SMTP, locally supplied Stripe keys, and new Cloudflare secret values. Uber Eats
card payment remains workflow-pending for this protected preview unless a
site-specific WcodeW Stripe adapter is added later.

## TripIt and Amazon GitHub deployment refresh

Recorded at: `2026-08-08T09:20:00Z`

In the current supervised conversation, the user explicitly requested that the
current offline-clone websites, especially TripIt and Amazon, be deployed from
GitHub through the repository-designed workflow to their corresponding public
review domains. This authorizes the Basic-Auth-protected, `noindex`, resettable
Cloudflare review deployments at `tripit.website-bench.com` and
`amazon.website-bench.com` from the exact pushed candidate.

The authorization does not mark either site technically-verified, authorize live
payments or real fulfillment, or convert the ephemeral Cloudflare SQLite state
into durable storage. Amazon remains test-payment-only; TripIt remains on its
deterministic `local-sandbox` payment adapter.
