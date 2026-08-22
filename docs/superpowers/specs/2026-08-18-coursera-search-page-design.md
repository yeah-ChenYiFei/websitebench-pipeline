# Coursera Deep Learning Search Page Design

## Goal

Reproduce the source-observed Coursera search state at
`/search?query=Deep%20Learning` for the `1191 × 979` desktop viewport, including
the English search chrome, the user-selected completed AI Overview, twelve
visible result cards, the filter drawer, working local filters and the required
impossible-query recovery state.

## Evidence and authority

The implementation is grounded in these retained artifacts:

- `source-search-deep-learning-playwright.json` and its `1191 × 4722` full-page
  screenshot for page order, card content, assistant rail and footer;
- `source-search-deep-learning-settled-playwright.json` for the settled state,
  which still showed `AI summary is loading...`;
- `source-search-filter-panel-playwright.json` and its screenshot for the open
  `Filter & Sort` drawer;
- `source-search-result-identities-playwright-v3.json` for eleven stable
  canonical result destinations;
- the first search screenshot for the Illinois Tech card, which disappeared
  from a later anonymous experiment;
- the user screenshot `屏幕截图 2026-08-18 220933.png` for the authoritative
  completed AI Overview, four starter cards, follow-up terms, wide top geometry
  and absence of the assistant composer.

The user screenshot supersedes the earlier loading experiment for the top
region. Its visible wording and course identities are transcribed directly;
no generated AI text is added. The older mixed Chinese/English implementation
and its unsupported recommendation copy are not source evidence.

## Selected approach

Use a dedicated search-page presentation module, template and route-scoped CSS
fed by a fixed source-evidence data set for the selected `Deep Learning` state.
Keep the existing catalog filter function for local interaction semantics, but
map matching catalog records into the source card presentation only where the
source identity is verified.

The retained loading captures remain historical A/B evidence, but no longer
control the selected top state. Omitting the AI region was rejected because the
user screenshot shows it prominently. Generating or paraphrasing the summary
was rejected; only the screenshot-visible copy is reproduced.

## Page structure and geometry

The route uses the existing English Coursera audience and navigation bars. The
top region uses a centered responsive shell, with a two-column AI layout on
desktop and the existing results grid below it. The assistant rail and composer
are absent in the user-selected state.

The main column is ordered as follows:

1. `AI Overview` with sparkle icon and collapse affordance.
2. `Understanding deep learning and how to get started`, followed by the exact
   screenshot-visible explanatory paragraph.
3. `Top courses to get started:` with four source-backed cards: Deep Learning,
   Neural Networks and Deep Learning, IBM Deep Learning with PyTorch, Keras and
   Tensorflow, and PyTorch for Deep Learning.
4. A right-side `You might follow up with...` collection containing the ten
   screenshot-visible search terms.
5. Divider, `All Results`, six standard filter chips and two screenshot-visible
   AI filter chips.
6. A full-width responsive result grid, an interstitial
   `What brings you to Coursera today?` panel after the sixth result, and the
   remaining six results. The retained `1191 × 979` source page uses three
   columns, while the user-supplied `2559 × 1471` wide state uses four. The grid
   uses the complete responsive content-shell width; it must not retain the old
   assistant-layout `699px` cap or squeeze four short cards into the `1191px`
   viewport.
7. The source-style multi-column footer.

No `Ask me anything` composer, assistant controls, synthetic chat transcript or
privacy card is rendered.

## Result identity contract

The default query presents these exact cards in order:

1. Deep Learning — DeepLearning.AI — `/specializations/deep-learning`
2. Neural Networks and Deep Learning — DeepLearning.AI —
   `/learn/neural-networks-deep-learning`
3. IBM Deep Learning with PyTorch, Keras and Tensorflow — IBM —
   `/professional-certificates/ibm-deep-learning-with-pytorch-keras-tensorflow`
4. PyTorch for Deep Learning — DeepLearning.AI —
   `/professional-certificates/pytorch-for-deep-learning`
5. Machine Learning — Multiple educators —
   `/specializations/machine-learning-introduction`
6. Introduction to Deep Learning & Neural Networks with Keras — IBM —
   `/learn/introduction-to-deep-learning-with-keras`
7. Deep Learning with PyTorch — IBM —
   `/search?query=Deep%20Learning%20with%20PyTorch`
8. IBM AI Engineering — IBM — `/professional-certificates/ai-engineer`
9. Deep Learning Engineering — Coursera —
   `/specializations/deep-learning-engineering`
10. Deep Learning with Python: CNN, ANN & RNN — EDUCBA —
    `/specializations/deep-learning-python-cnn-ann-rnn`
11. Learning Deep Learning — Pearson —
    `/specializations/pearson-learning-deep-learning-from-perception-to-large-language-models`
12. Deep Learning — Illinois Tech —
    `/search?query=Illinois%20Tech%20Deep%20Learning`

Card badges, skills, rating, review count, level, product type and duration
follow the full-page screenshot exactly. Card covers use the exact observed
source media where available. A lossless crop of the retained source screenshot
is the fallback for an experiment-only cover; mild softness is an accepted
temporary media limitation and must not be hidden by generated replacements.
Every result cover uses the source's approximately `16:9` media box, and all
twelve cover boxes remain equal in height at a given viewport. DeepLearning.AI,
IBM, the paired DeepLearning.AI/Stanford educator identity and Illinois Tech
use their retained local provider marks rather than generic placeholder tiles.

The four AI starter cards also use equal-height covers and a fixed two-line
title row so every `Best for:` description begins on the same baseline. The IBM
starter title follows the screenshot-visible truncation, `IBM Deep Learning
with PyTorch, Keras and…`, without changing the full result-card title.

## Filters and interactions

The chip row contains `Filter & Sort`, `Topic`, `Duration`, `Learning Product`,
`Language`, `Level`, `Deep Learning Core Techniques`, and `Deep Learning
Frameworks and Libraries`. Activating `Filter & Sort` opens a
right-side drawer over a dimmed page. The drawer is about `360px` wide and has:

- an expanded `Sort by` section with `Best Match` selected and `Newest`;
- collapsed sections for `Topic`, `Duration`, `Learning Product`, `Skills`,
  `Language`, `Level`, `Educator`, `Subtitles`, `Hands-on Learning`, and `Tools`;
- a blue `View` button and a disabled `Clear all` button fixed to the bottom.

The close button, page overlay and `View` button close the drawer. Filter
controls submit local GET query parameters and retain the search term. The
route accepts both source-facing `query` and the existing local `q` alias.
For the selected state, both aliases reproduce the screenshot-visible lowercase
search-field value `deep learning`.

## No-results recovery

`/search?query=zzzz-no-match-websitebench` renders an English no-results state
without fabricating matches. It keeps global navigation and provides visible
routes to clear filters, return to the Deep Learning search and browse the
general catalog. The no-results state may show source-backed recovery prompts,
but it must not label arbitrary catalog records as matches.

## Implementation boundaries

- Create a focused `search_page.py`, `templates/pages/search.html` and
  `static/search-page.css`; do not grow the old inline route markup. The filter
  drawer uses a CSS `:target` state so it remains functional under the clone's
  existing `script-src 'none'` content-security policy.
- Keep filtering pure and deterministic. This page introduces no account,
  backend, email, checkout, payment or database changes.
- All runtime assets are local. No remote image, font, iframe, script or source
  proxy is allowed.
- Preserve unrelated dirty work and make no commits.
- Do not add animations that are absent from the evidence. The drawer may use
  only the immediate state change observed by the source interaction.

## Verification

Focused tests assert pure-English copy, exact twelve-card order and destinations,
the selected completed AI copy and four starter identities, absence of the stale
loading state and assistant composer, query-alias behavior, filter state, drawer
controls, interstitial position and impossible-query recovery. Existing filter
semantics remain covered.

Playwright verification runs at `1191 × 979` for the default search, open filter
drawer and no-results state. It checks route, key text, geometry, card image
closure, console errors, failed requests, blocked requests and remote runtime
resources. At `1191px`, the first three cards share a row and the fourth begins
the next; all twelve covers are equal-height `16:9` boxes. A `2559 × 1471`
geometry regression checks that the first and fourth result cards share a row
and that the grid's left and right edges match the content shell. The final
visual comparison is diagnostic evidence and is judged alongside the retained
source screenshots.

## Known source limitation

The automated source experiment never exposed the completed AI Overview; the
user-provided screenshot is therefore the authority for that region. The later
anonymous source experiment also omitted the Illinois Tech result; its identity
and visible metadata remain grounded in the earlier retained full-page screenshot rather than being
silently replaced by the newer experiment.

The source destinations for `Deep Learning with PyTorch` and the Illinois Tech
`Deep Learning` card could not be recovered from the current experiment. With
the user's approval, those two cards temporarily route to exact local search
queries rather than to guessed course-detail paths. Their visual identities
remain source-grounded; this fallback is not presented as a verified canonical
destination.
