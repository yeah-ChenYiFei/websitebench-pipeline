# Coursera Data Science Card Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not dispatch subagents and do not commit.

**Goal:** Make the screenshot-visible Trending and Online degrees cards match the selected Coursera Data Science experiment exactly.

**Architecture:** Keep source facts in `data_science_page.py`, render optional evidence-backed provider logos through the existing Jinja macro, and add only sanitized local image crops. Preserve the current page structure and geometry.

**Tech Stack:** Python, Jinja2, CSS, Pillow/ImageMagick, pytest, WebsiteBench Playwright diagnostics.

## Global Constraints

- Authority is `docs/superpowers/specs/2026-08-18-coursera-data-science-card-identity-design.md`.
- Runtime UI remains pure English and remote-presentation-free.
- Do not invent cards, metadata, links, images or animation.
- Preserve unrelated dirty work and create no commit.

### Task 1: Card identity contract

**Files:**
- Modify: `materials/33/clone/tests/test_data_science_category.py`

**Interfaces:**
- Consumes: rendered `/browse/data-science` HTML.
- Produces: exact behavioral assertions for the two corrected collections.

- [x] Add one focused test that scopes each collection by its section marker and asserts exact title order, provider order, ratings, metadata, internal links, local covers, provider marks and badge count.
- [x] Run only the focused test and confirm it fails because the current Trending and degree identities differ.

### Task 2: Evidence-backed assets and card facts

**Files:**
- Create: `materials/33/clone/static/data-science/trending-business-consultants.png`
- Create: `materials/33/clone/static/data-science/trending-discover-prompting.png`
- Create: `materials/33/clone/static/data-science/trending-generative-ai-fundamentals.png`
- Create: `materials/33/clone/static/data-science/degree-pittsburgh.png`
- Create: `materials/33/clone/static/data-science/degree-leeds.png`
- Create: `materials/33/clone/static/data-science/logo-fractal.png`
- Create: `materials/33/clone/static/data-science/logo-colorado.png`
- Create: `materials/33/clone/static/data-science/logo-pittsburgh.png`
- Create: `materials/33/clone/static/data-science/logo-leeds.png`
- Modify: `materials/33/clone/data_science_page.py`
- Modify: `materials/33/clone/templates/pages/data_science.html`
- Modify: `materials/33/clone/static/data-science-category.css`
- Modify: `materials/33/source-evidence/data-science-card-crops-provenance.json`

**Interfaces:**
- Consumes: screenshot-visible crop rectangles and Playwright-observed internal paths.
- Produces: corrected `TRENDING` and `DEGREES` tuples plus optional `provider_logo` card data.

- [x] Create lossless cover and provider-mark crops and record exact pixel rectangles in provenance.
- [x] Add optional `provider_logo` to `_card` and render it in `provider_mark` when present.
- [x] Replace both card tuples with the exact evidence-backed identities and paths.
- [x] Apply the screenshot-observed `16:9` cover ratio only to Trending and Online degrees cards.
- [x] Run the focused identity test and confirm it passes.

### Task 3: Browser and regression verification

**Files:**
- Modify: `materials/33/scope/clone-data-science-category.json`
- Create: fresh reports under `materials/33/source-evidence/`.

**Interfaces:**
- Consumes: the running clone at `http://127.0.0.1:8044`.
- Produces: current diagnostic-only browser evidence at both required viewports.

- [x] Extend the clone scenario with exact Trending and degree card-count observations.
- [x] Run the focused Data Science tests and the existing public/desktop contracts.
- [x] Run fresh Playwright captures at `1191 x 979` and `1264 x 1312`.
- [x] Inspect screenshots, section order, image loading, network closure and console state; repair only evidence-backed differences.
