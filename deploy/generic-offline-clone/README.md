# Generic offline-clone backend deployment

This component packages one machine-validated offline clone with the site-bound
backend contract in `backend/runtime.json`. Descriptor v2 points at that single
contract instead of repeating database, mail and payment settings. Descriptor
v1 remains readable for existing sites and emits an explicit compatibility
warning.

For a new protected public-demo site, follow
[`docs/public-demo-new-site-deployment.md`](../../docs/public-demo-new-site-deployment.md).
It adds one site-bound descriptor and one fixed dispatcher; it never adds the
site to a batch deployment path.

`verification_complete` is a technical machine-verification state; it does not
express copyright, redistribution or legal authorization. The default is
dry-run. A real external change requires explicit `--yes`, the selected site's
machine preflight, and its own deployment checks.

## Profiles

| Profile | SQLite | Mail | Payment |
|---|---|---|---|
| `offline-harbor` | Site-exclusive and restart-persistent | Safe local outbox | `local-sandbox` |
| `cloudflare-review` | Ephemeral; rebuilt from seed | Redis + Resend through the effects gateway | Optional `stripe-test` |
| `docker-volume` | Site-exclusive named volume | Resend through the effects gateway | `local-sandbox` or `stripe-test` |

Cloudflare Container local disks are ephemeral. A public demonstration may reset
after sleep, restart or rebuild and must never be described as durable. It is an
anonymous `noindex` offline-clone sandbox, not a source-brand service. See the
[Cloudflare Container architecture](https://developers.cloudflare.com/containers/platform-details/architecture/).

The generated Compose stack has one app, one effects gateway, a site-specific
private network, a gateway-only egress network and a site-specific named
volume. Only the app mounts the volume. Provider secrets remain in the effects
gateway, and internal Redis/Resend/Stripe routes require a site-specific token.
For non-secret business mail, the app can send only a claimed structured
envelope to `resend.internal/business-emails`; the gateway revalidates the
frozen runtime template and renders the final text/HTML. It rejects arbitrary
HTML, rendered message bodies and secret-bearing OTP purposes. A business-mail
failure leaves a retryable outbox job and never reverses a committed order.

## Configure

Use `deployment.v2.example.json`, `deployment.docker-volume.example.json` and
`backend-runtime.example.json` as the generic examples.
`deployment.amazon.v2.json` is the migrated Amazon descriptor.
`deployment.edx.v2.json` is the edX Stripe-test candidate descriptor. Its
Cloudflare path requires the current hash-bound edX payment scope and explicit
profile overlay.
`deployment.petfinder.v2.json` packages the site-isolated Petfinder clone with
Redis/Resend account and receipt mail plus Stripe test Checkout. Its support
checkout is explicitly test-only and the Cloudflare SQLite state is ephemeral.
`deployment.capterra.v2.json` packages the site-isolated Capterra clone for the
`docker-volume` profile with its canonical account, mail, local-sandbox payment,
database and volume identities.
`deployment.tripit.v2.json` packages the site-isolated TripIt clone with
Redis/Resend account, share-invite, import-receipt and Pro-receipt mail. Its
Pro purchase runs through the deterministic `local-sandbox` payment adapter, so
the Stripe test gateway stays dormant and no Stripe secret is provisioned. The
Cloudflare SQLite state is ephemeral and rebuilt from seed.
Each v2 deployment descriptor contains only deployment packaging data plus:

```json
{
  "schema_version": "websitebench.generic-public-clone-deployment.v2",
  "backend_runtime": "../../materials/example/backend/runtime.json",
  "deployment_profile": "cloudflare-review"
}
```

The runtime contract freezes `site_id`, label, public origin, the safe database
path, migration/seed hook names, structured branded mail copy, payment
currency, return/webhook paths, secret binding names and profile persistence
semantics. v2 derives identity/domain from that contract. Environment
variables may supply secrets and the profile's fixed container data-root
mapping, but may not override site identity, database filename, host/path,
currency or other frozen semantics.

Preparation rejects path traversal, symlinks, unpinned Python dependencies,
unknown fields, invalid runtime contracts, duplicate support destinations and
unsafe profile combinations. The deployment digest covers the candidate,
support files, shared auth/site-backend code, Worker/effects gateway code,
Docker runtime and generator scripts. Windows `file:` URLs are converted with
Node's platform-aware URL/path APIs, including Unicode workspace paths.
For descriptor v2, Node delegates backend-runtime validation to the canonical
Python `websitebench.site_backend` validator; it does not maintain a second,
weaker interpretation of hooks, mail placeholders, sandbox outcomes, Stripe
settings or fixed profile semantics.

## Prepare and verify

```powershell
cd deploy/generic-offline-clone
npm ci
npm test

# Validate and hash the exact Amazon candidate without external effects.
node scripts/prepare.mjs --config deployment.amazon.v2.json --check-only

# Default-safe Cloudflare review dry-run.
node scripts/deploy.mjs --config deployment.amazon.v2.json --dry-run
```

For `docker-volume`, the same dry-run renders and validates Compose:

```powershell
node scripts/deploy.mjs --config deployment.docker-volume.example.json --dry-run
```

Before executing the candidate command, every v2 container validates the
runtime, resolves only its exactly declared migration/seed hooks, and
initializes or verifies the site binding in that site's `/data` mapping.
A volume bound to another `site_id` fails before public traffic. Generated
Compose escapes runtime `${code}`/`${minutes}` mail placeholders as `$$`, so
Compose does not consume them as host environment variables.

Normal preflight never performs legacy migration, even when the
contract records that a legacy migration is possible. An existing unbound
database fails closed. The site owner must run its separate, explicit,
provenance-checking migration command first; the next ordinary preflight then
accepts only the newly bound database.

An actual Compose build/replacement requires a running Docker daemon. Verify
account and order persistence across a container replacement before treating a
`docker-volume` profile as durable evidence.

## Real deployment

Real deployment is opt-in and runs the selected candidate's preparation before
invoking the provider command:

```powershell
node scripts/deploy.mjs `
  --config deployment.local.json `
  --yes
```

Required provider secret names come from the runtime contract and generated
configuration. Do not put secret values, raw provider errors, OTPs or payment
credentials in descriptors, SQLite, logs or evidence. `stripe-test` accepts
only test keys and opaque Session identifiers. A Session identifier alone
cannot approve a flow: the app must use the provider-verified payment
interface, which authenticates/retrieves the Session and rechecks all frozen
facts. Card data is never an app/backend input.

After a real deployment, record the exact candidate/image/Worker identity,
URL, profile and smoke-test evidence. The command reports
`deployed-machine-validated` after preparation and the provider command
complete; preserve the site's separate technical-verification evidence.

For an anonymous public profile, set a public `TURNSTILE_SITE_KEY` Worker
variable and a `TURNSTILE_SECRET_KEY` Worker secret. The Worker verifies
Turnstile before it forwards the registration send-code request, fails closed
when verification is unavailable, and removes the token before proxying to the
Container. Existing Redis email/IP/attempt limits and site-scoped mail
templates remain in force.
