# tripit source-assets rights review

Provenance: every file under `source-assets/2026-08-03.tripit-r1/` was
captured on 2026-08-04 as an HTTP response while rendering the anonymous
public pages of https://www.tripit.com/ inside the frozen capture
environment (see `source-current/2026-08-03.tripit-r1/capture-metadata.json`).
No asset was sourced from anywhere other than the live site's own asset
graph; `manifest.json` binds each declared payload to its origin URL, byte
size, and sha256.

Deliberate, documented normalizations (the only edits to captured bytes):

- `sites/tripit/files/acn/2022-06/illu-howitworks-hero-us.svg` — the source
  declares float `width="786.81" height="561.96"` and no `viewBox`. A
  `viewBox="0 0 786.81 561.96"` was added: this is exactly the implicit
  viewport a no-`viewBox` SVG uses when rendered at its intrinsic size, so the
  rendering is unchanged (off-canvas geometry stays clipped as before) while
  the offline-clone asset verifier can now derive integer dimensions
  (787 x 562). Both mirror copies carry the identical edit and the manifest
  entry rebinds bytes/sha256/dimensions to the normalized file.

Assets served byte-exact but outside the verified manifest closure: the two
`.ico` favicons (`/favicon.ico?v=6a073a4` and
`/themes/custom/tripit_theme/favicon.ico`) carry no dimensions the asset
verifier can derive (ICO is outside its PIL suffix set), so they are removed
from `manifest.json` and served unmodified from `clone/static/site/favicon/`.
Their bytes are the captured payloads verbatim; the captured originals remain
under `source-assets/2026-08-03.tripit-r1/` as evidence.

Rights posture:

- TripIt, the TripIt logo, and all captured imagery, copy, CSS, JavaScript,
  and font files are the property of their respective owners (TripIt /
  Concur Technologies / SAP and their font licensors, including the
  Proxima Nova family delivered through the site's own webfont pipeline).
- These captures exist solely as benchmark evidence for offline-clone
  fidelity evaluation inside this repository's controlled workflow.
- `release-ready` and any passing gate status assert **technical fidelity
  only** — they do not assert or imply any copyright, trademark, or
  redistribution authorization, matching the repository-wide policy
  (AGENTS.md / docs source-evidence policy).
- Public redistribution of these assets is explicitly out of scope
  (`scope/purpose.json` → out_of_scope) and the deployed review candidate
  sits behind basic-auth on an ephemeral review profile.

Runtime policy: `manifest.json` sets `remote_runtime_policy: "forbidden"` —
the clone serves only the local mirrored copies under
`clone/static/assets/` and never fetches from tripit.com or any third-party
origin at runtime.
