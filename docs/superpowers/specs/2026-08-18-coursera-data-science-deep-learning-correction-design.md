# Coursera Data Science Deep Learning Correction Design

## Authority

The user-supplied public screenshot `屏幕截图 2026-08-18 194359.png` is the
authority for this Data Science A/B state. It shows the exact local sequence:

1. `Trending now`
2. `Core skills`
3. `Enhance Your Deep Learning Skills with Neural Networks`
4. `Online degrees`

The current anonymous source route and the earlier retained full-page capture
represent different experiments and must not override this user-selected
state. The four Deep Learning cards, links, images, ratings, review counts and
metadata are independently supported by the existing read-only Playwright
evidence for `/browse`.

## Correction

- Remove the three collections currently placed between `Core skills` and
  `Online degrees` in the clone's Data Science state.
- Insert the source-observed four-card Deep Learning collection in that exact
  location.
- Reuse the existing local DeepLearning.AI media rather than generating or
  re-cropping equivalent images.
- Preserve the `1191 x 979` geometry already verified for the Data Science
  page, while using a `16:9` image ratio so the collection also matches the
  supplied wider screenshot.
- Do not change the partially shown degree titles or other routes in this
  correction. The screenshot-visible Trending differences are recorded for a
  separate evidence-backed detail pass rather than bundled into the missing
  section fix.

## Verification

- A source-identity test must fail before implementation and assert section
  order, all four card identities, links, local image paths, ratings and exact
  card count.
- Focused HTTP tests and the existing public/desktop contracts must pass.
- A fresh local Playwright run must report no console errors, failed requests,
  blocked requests, missing images or remote presentation resources.
- No commit is authorized.
