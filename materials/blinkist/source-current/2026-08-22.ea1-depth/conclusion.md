# EA1 depth-first source conclusion

- Source: `https://www.blinkist.com`; actor: authenticated member; channel: human-local Edge CDP.
- Capture exited `0` after the final retry. The CDP endpoint was not persisted. The user-owned Edge process was not closed; only the temporary capture page and CDP connection were closed.
- Mutation boundary: read-only. The capture never activated `Save to Library`, `Unlock with Premium`, subscription, payment, email, logout, or account-setting controls.

## P0 traversal

1. `https://www.blinkist.com/en/app/for-you`, `for-you/default`, desktop `1034x947`.
2. The For You page contains a directly visible search input with placeholder `Blinks, Guides, Shortcasts or Collections`. No separate visible search-entry control was found; this is the only unavailable item.
3. Fill public query `Atomic Habits`, `search/results`, same desktop viewport. Result observed: `Atomic Habits`, `James Clear`, `25 min`, `4.6`.
4. Open the result: `https://www.blinkist.com/app/books/atomic-habits-en`, `book-detail/default`, desktop `1034x947` and mobile `390x844`.
5. Detail visibly contains `Save to Library` (observed only), `Unlock with Premium`, `Atomic Habits`, `James Clear`, `Narrated by Amanda Mahr`, `4.6 (23456 ratings)`, `25 mins`, `7 Key ideas`, `Audio & text`, `What's it about?`, `Personal Development`, `Psychology`, `About the author`, `Share with friends`, `Buy on Amazon`, `Similar Blinks`, and `Trending` rails.
6. `https://www.blinkist.com/en/app/library`, `library/current-member-state`, desktop `1440x900` and mobile `390x844`. The navigation visibly includes `Saved` and a `saved-link`; the current saved collection was observed without changing it.

## Artifacts

- `summary.json`: six checkpoints, one unavailable surface.
- `route-state-viewport.json`: visit order and route/state/viewport matrix.
- `dom-geometry.json`: sanitized visible element structure and bounding boxes.
- `visible-copy.json`: sanitized visible text, labels, placeholders and test IDs.
- `unavailable.json`: only the missing separate search-entry control.
- `screenshots/01-for-you-desktop.png`
- `screenshots/02-search-atomic-habits-desktop.png`
- `screenshots/03-atomic-habits-detail-desktop.png`
- `screenshots/04-atomic-habits-detail-mobile.png`
- `screenshots/05-my-library-desktop.png`
- `screenshots/06-my-library-mobile.png`

Artifacts contain no credentials, cookies, tokens, authorization headers, browser profile, storage state, input values, request bodies, payment data or real email values. The capture script is retained only inside this EA1 directory.

