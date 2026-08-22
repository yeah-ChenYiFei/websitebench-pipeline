# Coursera Data Science Deep Learning Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not dispatch subagents and do not commit.

**Goal:** Make the Data Science category reproduce the user-selected sequence and exact four-card Deep Learning collection.

**Architecture:** Keep the source facts in `data_science_page.py`, render them through the existing Jinja card macro, and add only route-scoped CSS. Reuse local media already captured for the Browse and Deep Learning pages.

**Tech Stack:** Python, Jinja2, CSS, pytest, WebsiteBench Playwright diagnostics.

## Global Constraints

- Authority is `docs/superpowers/specs/2026-08-18-coursera-data-science-deep-learning-correction-design.md`.
- Runtime UI remains pure English and remote-presentation-free.
- Do not invent cards, animations, links, ratings or metadata.
- Preserve unrelated dirty work and create no commit.

### Task 1: Source-identity contract and collection correction

**Files:**
- Modify: `materials/33/clone/tests/test_data_science_category.py`
- Modify: `materials/33/clone/data_science_page.py`
- Modify: `materials/33/clone/templates/pages/data_science.html`
- Modify: `materials/33/clone/static/data-science-category.css`
- Modify: `materials/33/scope/clone-data-science-category.json`

**Interfaces:**
- Consumes: existing local Deep Learning images and source-observed card facts.
- Produces: `DEEP_LEARNING` card tuple and `.ds-deep-learning` rendered section.

- [x] Add a failing HTTP test asserting `Core skills < Deep Learning < Online degrees`, four exact titles, four exact links/images, ratings, review counts, and absence of the three conflicting collection headings.
- [x] Run the new test and verify it fails because the Deep Learning heading is absent.
- [x] Add the four source-observed cards and render the collection immediately after `Core skills`.
- [x] Remove the three conflicting collections from this selected Data Science state.
- [x] Add route-scoped `16:9` Deep Learning card geometry and the wider-screen `24px` grid gap observed in the supplied screenshot.
- [x] Run focused HTTP tests and verify they pass.
- [x] Extend the local browser scenario with the heading, card-count and section-order-adjacent observations supported by the schema.
- [x] Run a fresh Playwright capture, inspect geometry/network/image state, and report the evidence without committing.
