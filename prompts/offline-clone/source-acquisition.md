# Source acquisition brief

Work in the current repository and follow
`docs/source-evidence-access-policy.md`.

Use exactly this configured source scope:

- site ID: `<site-id>`
- allowed first-party, third-party/external and internal origins: `<origins>`
- pages/states/viewports: `<matrix>`
- available access mode or reusable authenticated browser context: `<access>`
- retention limits: `<limits>`

Downloading in-scope media and files and taking screenshots is allowed across
all configured surfaces. Reuse the supplied authenticated browser context until
it expires or the task ends. Never persist credentials, cookies, tokens,
browser profiles, payment data or sensitive form values.

Use the configured WebsiteBench/Playwright browser path for route/state and text
exploration, DOM/accessibility inspection, targeted network/console/frame
inspection, navigation, interaction, screenshots, geometry, assets and formal
capture.

Create a v2 spec from `examples/offline-clone/source-acquisition.example.json`
and run `websitebench-workflow acquire-source` for supported rows. Use browser
capture for authenticated or interactive rows and record only a sanitized
runtime/context identity. Do not expand allowed origins, bypass access controls
or trigger destructive, financial, publication, messaging or unrelated
production effects.

Return exact commands, spec/report/output paths and hashes, captured and
source-limited rows, blocked requests, missing resources and evidence limits.
