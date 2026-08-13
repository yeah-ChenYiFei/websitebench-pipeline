# Browserbase + Chrome DevTools MCP

`scripts/browserbase-chrome-devtools-mcp` creates a Browserbase session, polls
the session live-URLs endpoint for its debug `wsUrl`, and starts
`chrome-devtools-mcp@1.6.0` against that WebSocket. It does not use the session
creation response's `connectUrl`, because that endpoint is not a reliable
Chrome DevTools MCP connection target.

The launcher never writes or prints the Browserbase API key, API response body,
signed WebSocket URL, cookies, or authorization headers. Its stderr is limited
to lifecycle stages, HTTP status codes, and redacted failures. Temporary API
responses are stored in a mode-0700 temporary directory and removed on exit.

The Codex user configuration contains a `browserbase-chrome` MCP server that
points to this script. Its startup timeout is 90 seconds. Start a new Codex
process after changing the launcher or MCP settings:

```sh
codex mcp list
codex
```

When `BROWSERBASE_CDP_URL` is set to an existing `wss://` debug URL, the script
reuses it and creates no session. Otherwise it creates exactly one session
using the inherited `BROWSERBASE_API_KEY`. Browserbase infers the sole project
available to a key; `BROWSERBASE_PROJECT_ID` remains available for keys that
can access multiple projects. Other optional settings are
`BROWSERBASE_REGION` and `BROWSERBASE_SESSION_TIMEOUT`.

For an existing interactive/login session, prefer the non-sensitive
`BROWSERBASE_SESSION_ID`. The launcher resolves its debug `wsUrl` through the
Browserbase API, never prints that signed URL, and never releases a session it
did not create.

New sessions use `keepAlive=false` by default. On Chrome DevTools MCP exit the
launcher also requests `REQUEST_RELEASE`, so a failed startup does not leave a
session running. `BROWSERBASE_KEEP_ALIVE=true` is an explicit opt-in that
preserves a successfully connected session after a clean MCP disconnect; a
failed MCP process is still released. Debug readiness is always bounded to 15
seconds.

Browserbase CAPTCHA solving is explicitly enabled and its supported ad blocker
is enabled to reduce anonymous-source telemetry. The Capterra evidence client
still enforces its own GET/HEAD observation gate; `blockAds` is not treated as
proof that non-read traffic was absent.

The launcher prefers the repository install or an existing npm exec cache and
pins the fallback package to `chrome-devtools-mcp@1.6.0`, so npm registry
metadata is not required on every MCP restart.
