# Homepage and local navigation repair — 2026-09-04

The homepage previously rendered an expanded movie grid and omitted several source sections. Movies and other inner pages used an obsolete header, and the four main destination links left the clone. This revision restores the captured homepage structure, shares the six-entry Fandango header, and supplies local Theaters, FanStore, Streaming and Movie News landing pages.

This branch retains the original Fandango implementation commit from PR #176. That PR has not merged into `sites/fandango`, so the complete PR diff includes the original site, its unchanged workflow/Harbor files, and this repair. The repair itself is limited to `materials/fandango`. Formal human trajectories and vendored backend contracts are unchanged.

## Changes

- Restore the homepage's missing free movies, features, event banner, offers, compact poster strip and full footer. Use single-row movie carousels and six compact theater cards; match the supplied screenshot's content and shell rather than replacing it with current promotional content.
- Share Movies / Theaters / FanStore / Streaming / Movie News / Sign In/Join navigation across existing Fandango pages. Preserve existing search, account and New York booking demonstrations.
- Add the Los Angeles `90001` theater directory, date/chain/theater filters and local saved theaters. Preserve explicit switching to the existing `10003` data without requesting geolocation.
- Add FanStore landing/catalog/search/filter/product/variant/cart views, using 244 captured products and 1,220 source SKUs. Compute cart totals server-side and persist through the existing actor-state integration.
- Add Streaming's hero and 26 content rows, including wide Spotlight cards, search/details and a local library. Add Movie News carousels, natural-ratio news cards and load-more behavior.
- Package 108 homepage and 1,168 navigation media/font assets locally; retain public source-to-file mappings alongside this report. No runtime source API or external checkout integration is added.

## Verification and reproduction

From the clone directory, use the existing Python requirements and an isolated, writable database path ending in `fandango.sqlite3`:

```sh
export WEBSITEBENCH_SITE_BACKEND_DATABASE=/absolute/writable/test-directory/fandango.sqlite3
python -m pytest -q tests
python -m uvicorn app:app --host 127.0.0.1 --port 19489
```

In a separate shell, run the existing browser regression script with `--base http://127.0.0.1:19489`. Its path is `materials/fandango/tools/validate_local_ui.py` from the repository root. A compatible Chromium installation is required.

- Fresh PR worktree: 14 backend tests and 23 existing browser traces pass; see `pr-backend-tests.txt` and `pr-ui-results.json` in this directory.
- JavaScript syntax and Python compilation pass. The application is FastAPI plus static files; there is no npm production build step.
- All 1,168 new navigation assets decode successfully. Homepage static delivery and carousel/region/search checks were also verified during the repair.
- Browser checks cover local navigation, store search/variant/cart persistence, theater date and location changes, streaming library controls, and news load-more. Desktop and 390×844 mobile layouts were inspected without unexpected page overflow.
- The shared `verify` diagnostic's static section completes with no findings, but live is **incomplete** because its automatic startup cannot open the configured database. It validates the legacy 22-asset manifest; new assets have a separate decode report. This is not reported as a clean overall diagnostic or as proof of complete fidelity.
- Backend contract: `backend/runtime.json`, `site_id=fandango`, isolated `fandango.sqlite3`; existing local-sandbox payment adapter and offline-harbor profile. Registration/password-reset mail purposes remain configured in the original runtime; no real mail, payment or production account operation was performed.

The local preview and formal PR are separate from deployment. No public deployment or merge is part of this change.

## Visual evidence

Screenshots in this directory include `home-desktop-final.png`, `movies-desktop.png`, `fanstore-desktop-top.png`, `streaming-desktop-top.png`, `theaters-desktop-top.png`, `movie-news-desktop-top.png` and mobile counterparts. Homepage reference comparison used a 2560px CSS viewport, DPR 1, anonymous state and ZIP 90001, cross-checked with source computed styles; the supplied PNG alone cannot establish all original browser metadata. The other desktop comparisons used 1280×720 or 1440×900 at DPR 1, matching their source captures.

The browser's full-page export repeatedly failed for the new destination pages, so their images are viewport segments, not fabricated stitched captures. The homepage full-page image was captured successfully.

Public source evidence was observed on `www.fandango.com`, `store.fandango.com` and `athome.fandango.com`. Product variants came from the corresponding public product JSON. Snapshot content, prices and availability are not live data.

## Remaining fidelity gaps

- Most article/gallery/video detail pages have captured cover/title and a clear local limitation notice, not full editorial text or licensed video playback. The Zach article includes a verified short summary. Streaming Rent & Buy has no fully captured rental catalog.
- Several store policy/support destinations remain local explanatory pages. Real store checkout and newsletter delivery are intentionally absent. Product descriptions are excerpts. Featured's first 24 products are verified; later catalog ordering uses captured best-selling order.
- Los Angeles showtime data covers September 4–5, 2026. Other dates show missing-data states. No verified LA seat inventory or ticket prices were captured; the original New York demonstration remains functional.
- One homepage Zach offer image uses a clearly identified crop of the supplied target screenshot because its original full-resolution campaign image was unavailable.
- The four requested main navigation destinations are local. This does not claim that every secondary promotion, footer service, article or external brand has been fully replicated.
- Existing source/trajectory evidence is preserved. Passing tests and the greater page length do not establish full website acceptance.
