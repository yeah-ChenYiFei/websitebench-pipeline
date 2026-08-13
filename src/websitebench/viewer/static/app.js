const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";

function setupTaskAtlas() {
  const rowsContainer = document.querySelector("#task-rows");
  if (!rowsContainer) return;
  const rows = [...rowsContainer.querySelectorAll("[data-task-row]")];
  const search = document.querySelector("#task-search");
  const source = document.querySelector("#source-filter");
  const category = document.querySelector("#category-filter");
  const stage = document.querySelector("#stage-filter");
  const sort = document.querySelector("#task-sort");
  const count = document.querySelector("#visible-count");

  const initial = new URLSearchParams(window.location.search);
  for (const [control, parameter] of [[source, "source"], [category, "category"], [stage, "stage"]]) {
    const value = initial.get(parameter);
    if (control && value && [...control.options].some((option) => option.value === value)) {
      control.value = value;
    }
  }

  const update = () => {
    const query = search.value.trim().toLowerCase();
    for (const row of rows) {
      const visible =
        (!query || row.dataset.search.includes(query)) &&
        (!source.value || row.dataset.source === source.value) &&
        (!category.value || row.dataset.category === category.value) &&
        (!stage.value || row.dataset.stage === stage.value);
      row.hidden = !visible;
    }
    const numeric = (row, key) => Number(row.dataset[key] || -1);
    rows.sort((left, right) => {
      if (sort.value === "readiness") return numeric(right, "missing") - numeric(left, "missing");
      if (sort.value === "official") return numeric(right, "official") - numeric(left, "official");
      return left.dataset.name.localeCompare(right.dataset.name);
    });
    rows.forEach((row) => rowsContainer.append(row));
    count.textContent = rows.filter((row) => !row.hidden).length;
  };
  [search, source, category, stage, sort].filter(Boolean).forEach((control) =>
    control.addEventListener(control === search ? "input" : "change", update),
  );
  update();

  const compare = document.querySelector("#compare-selected");
  const checks = [...document.querySelectorAll(".compare-check")];
  if (!compare) return;
  checks.forEach((check) =>
    check.addEventListener("change", () => {
      const selected = checks.filter((item) => item.checked);
      if (selected.length > 4) {
        check.checked = false;
        return;
      }
      const current = checks.filter((item) => item.checked);
      compare.disabled = current.length < 2;
      compare.querySelector("span").textContent = current.length;
    }),
  );
  compare.addEventListener("click", () => {
    const keys = checks.filter((item) => item.checked).map((item) => item.value);
    if (keys.length >= 2 && keys.length <= 4) {
      window.location.assign(`/compare?keys=${encodeURIComponent(keys.join(","))}`);
    }
  });
}

const lines = (value) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

function setupReviewForm() {
  const form = document.querySelector("#review-form");
  if (!form) return;
  const status = document.querySelector("#review-status");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.className = "";
    status.textContent = "Saving…";
    const values = new FormData(form);
    const dimensions = {};
    form.querySelectorAll("[data-review-dimension]").forEach((fieldset) => {
      const name = fieldset.dataset.reviewDimension;
      dimensions[name] = {
        rating: values.get(`${name}-rating`),
        notes: values.get(`${name}-notes`),
        evidence_refs: lines(values.get(`${name}-evidence`)),
      };
    });
    const body = {
      expected_revision: Number(form.dataset.revision),
      review: {
        reviewer: values.get("reviewer"),
        decision: values.get("decision"),
        visibility: values.get("visibility"),
        dimensions,
        notes: values.get("notes"),
        evidence_refs: lines(values.get("evidence_refs")),
      },
    };
    try {
      const response = await fetch(`/api/reviews/${encodeURIComponent(form.dataset.itemKey)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || result.error || "Review save failed");
      form.dataset.revision = result.revision;
      status.className = "save-success";
      status.textContent = `Saved revision ${result.revision}.`;
    } catch (error) {
      status.className = "save-error";
      status.textContent = error.message;
    }
  });
}

function stopBlink(review) {
  if (review._blinkTimer) window.clearInterval(review._blinkTimer);
  review._blinkTimer = null;
  review.classList.remove("blink-candidate");
}

function setVisualMode(review, mode) {
  stopBlink(review);
  review.dataset.mode = mode;
  review.querySelectorAll("[data-visual-mode]").forEach((button) =>
    button.classList.toggle("active", button.dataset.visualMode === mode),
  );
  if (mode === "blink") {
    review._blinkTimer = window.setInterval(
      () => review.classList.toggle("blink-candidate"),
      650,
    );
  }
}

function setupVisualReview() {
  const picker = document.querySelector("[data-capture-picker]");
  const reviews = [...document.querySelectorAll("[data-capture]")];
  if (picker) {
    picker.addEventListener("change", () => {
      reviews.forEach((review) => {
        const active = review.dataset.capture === picker.value;
        review.classList.toggle("hidden", !active);
        if (!active) stopBlink(review);
      });
    });
  }
  reviews.forEach((review) => {
    let zoom = 1;
    const stage = review.querySelector("[data-visual-stage]");
    const zoomLabel = review.querySelector("[data-zoom-label]");
    review.querySelectorAll("[data-visual-mode]").forEach((button) =>
      button.addEventListener("click", () => setVisualMode(review, button.dataset.visualMode)),
    );
    review.querySelectorAll("[data-zoom]").forEach((button) =>
      button.addEventListener("click", () => {
        zoom = Math.min(2, Math.max(0.5, zoom + (button.dataset.zoom === "in" ? 0.25 : -0.25)));
        stage.style.setProperty("--zoom", zoom);
        zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
      }),
    );
    stage.addEventListener("pointermove", (event) => {
      if (review.dataset.mode !== "split") return;
      const bounds = stage.getBoundingClientRect();
      const position = Math.min(100, Math.max(0, ((event.clientX - bounds.left) / bounds.width) * 100));
      stage.style.setProperty("--split", `${position}%`);
    });
  });
}

function setupComparePicker() {
  const select = document.querySelector(".compare-picker select[multiple]");
  if (!select) return;
  select.addEventListener("change", () => {
    const selected = [...select.selectedOptions];
    if (selected.length > 4) selected.at(-1).selected = false;
  });
}

function setupRouteExplorer() {
  const explorer = document.querySelector("[data-route-explorer]");
  if (!explorer) return;
  const filters = [...explorer.querySelectorAll("[data-evidence-filter]")];
  const routes = [...explorer.querySelectorAll("[data-route-evidence]")];
  const count = explorer.querySelector("[data-route-count]");
  filters.forEach((filter) => {
    filter.addEventListener("click", () => {
      filters.forEach((button) => button.classList.toggle("active", button === filter));
      let visible = 0;
      routes.forEach((route) => {
        const matches =
          filter.dataset.evidenceFilter === "all" ||
          route.dataset.routeEvidence === filter.dataset.evidenceFilter;
        route.hidden = !matches;
        if (matches) visible += 1;
      });
      if (count) count.textContent = visible;
    });
  });
}

function setReplayStep(panel, requested) {
  const steps = [...panel.querySelectorAll("[data-replay-step]")];
  if (!steps.length) return;
  const index = Math.min(steps.length - 1, Math.max(0, requested));
  steps.forEach((step, stepIndex) => {
    const listItem = step.closest("li");
    listItem.classList.toggle("active", stepIndex === index);
    listItem.classList.toggle("complete", stepIndex < index);
    step.querySelector("i").textContent =
      stepIndex < index ? "observed" : stepIndex === index ? "current" : "queued";
  });
  panel.dataset.replayIndex = index;
  const current = panel.querySelector("[data-replay-current]");
  const progress = panel.querySelector("[data-replay-progress]");
  if (current) current.textContent = index + 1;
  if (progress) progress.style.width = `${((index + 1) / steps.length) * 100}%`;
  const previous = panel.querySelector("[data-replay-prev]");
  const next = panel.querySelector("[data-replay-next]");
  if (previous) previous.disabled = index === 0;
  if (next) {
    next.disabled = index === steps.length - 1;
    next.textContent = index === steps.length - 1 ? "Journey complete" : "Next step →";
  }
}

function setupJourneyReplay() {
  const player = document.querySelector("[data-journey-replay]");
  if (!player) return;
  const tabs = [...player.querySelectorAll("[data-journey-tab]")];
  const panels = [...player.querySelectorAll("[data-journey-panel]")];
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((button) => button.classList.toggle("active", button === tab));
      panels.forEach((panel) =>
        panel.classList.toggle("hidden", panel.dataset.journeyPanel !== tab.dataset.journeyTab),
      );
    });
  });
  panels.forEach((panel) => {
    const steps = [...panel.querySelectorAll("[data-replay-step]")];
    steps.forEach((step, index) =>
      step.addEventListener("click", () => setReplayStep(panel, index)),
    );
    panel.querySelector("[data-replay-prev]")?.addEventListener("click", () =>
      setReplayStep(panel, Number(panel.dataset.replayIndex || 0) - 1),
    );
    panel.querySelector("[data-replay-next]")?.addEventListener("click", () =>
      setReplayStep(panel, Number(panel.dataset.replayIndex || 0) + 1),
    );
    setReplayStep(panel, 0);
  });
}

const reviewStatuses = [
  "open",
  "triaged",
  "repairing",
  "needs_evidence",
  "resolved",
  "known_difference",
  "dismissed",
  "stale",
];
const inactiveReviewStatuses = new Set(["resolved", "known_difference", "dismissed"]);

function reviewLabel(value) {
  return value.replaceAll("_", " ");
}

function reviewStatus(root, message, kind = "") {
  const status = root.querySelector("[data-review-mode-status]");
  status.className = kind;
  status.textContent = message;
}

function reviewBadge(value, className) {
  const badge = document.createElement("span");
  badge.className = `state ${className}`;
  badge.textContent = reviewLabel(value);
  return badge;
}

function reviewTextBlock(label, value) {
  const block = document.createElement("div");
  block.className = "review-finding-text";
  const heading = document.createElement("strong");
  heading.textContent = label;
  const body = document.createElement("p");
  body.textContent = value;
  block.append(heading, body);
  return block;
}

function reviewReferences(label, values) {
  if (!values.length) return null;
  const block = document.createElement("div");
  block.className = "review-evidence-refs";
  const heading = document.createElement("strong");
  heading.textContent = label;
  block.append(heading);
  values.forEach((value) => {
    const code = document.createElement("code");
    code.textContent = value;
    block.append(code);
  });
  return block;
}

function reviewTarget(target) {
  return [
    target.checkpoint && `checkpoint ${target.checkpoint}`,
    target.viewport && `viewport ${target.viewport}`,
    target.route && `route ${target.route}`,
    target.role && `role ${target.role}`,
    target.state && `state ${target.state}`,
  ].filter(Boolean).join(" · ");
}

async function reviewRequest(url, options = {}) {
  const response = await fetch(url, options);
  let result;
  try {
    result = await response.json();
  } catch (_error) {
    result = {};
  }
  if (!response.ok) {
    const error = new Error(result.detail || result.error || "Review Mode request failed");
    error.status = response.status;
    throw error;
  }
  return result;
}

function reviewResolutionForm(root, finding) {
  const form = document.createElement("form");
  form.className = "review-resolution-form";
  form.dataset.findingId = finding.finding_id;

  const statusLabel = document.createElement("label");
  const statusHeading = document.createElement("span");
  statusHeading.textContent = "Status";
  const status = document.createElement("select");
  status.name = "status";
  reviewStatuses.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = reviewLabel(value);
    option.selected = value === finding.status;
    status.append(option);
  });
  statusLabel.append(statusHeading, status);

  const summaryLabel = document.createElement("label");
  const summaryHeading = document.createElement("span");
  summaryHeading.textContent = "Resolution / disposition";
  const summary = document.createElement("textarea");
  summary.name = "summary";
  summary.rows = 2;
  summary.maxLength = 10000;
  summary.value = finding.resolution.summary;
  summaryLabel.append(summaryHeading, summary);

  const evidenceLabel = document.createElement("label");
  const evidenceHeading = document.createElement("span");
  evidenceHeading.textContent = "Resolution evidence";
  const evidence = document.createElement("textarea");
  evidence.name = "evidence_refs";
  evidence.rows = 2;
  evidence.value = finding.resolution.evidence_refs.join("\n");
  evidenceLabel.append(evidenceHeading, evidence);

  const save = document.createElement("button");
  save.className = "secondary";
  save.type = "submit";
  save.textContent = "Save disposition";
  form.append(statusLabel, summaryLabel, evidenceLabel, save);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    reviewStatus(root, `Saving ${finding.finding_id}…`);
    const values = new FormData(form);
    try {
      const session = await reviewRequest(
        `${root.dataset.findingsUrl}/${encodeURIComponent(finding.finding_id)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
          body: JSON.stringify({
            expected_revision: root._reviewSession.revision,
            finding: {
              status: values.get("status"),
              resolution: {
                summary: values.get("summary"),
                evidence_refs: lines(values.get("evidence_refs")),
              },
            },
          }),
        },
      );
      renderReviewSession(root, session);
      reviewStatus(root, `Saved ${finding.finding_id}.`, "save-success");
    } catch (error) {
      if (error.status === 409) await loadReviewSession(root);
      reviewStatus(root, error.message, "save-error");
    } finally {
      save.disabled = false;
    }
  });
  return form;
}

function renderReviewFindings(root) {
  const container = root.querySelector("[data-review-findings]");
  const filter = root.querySelector("[data-review-status-filter]").value;
  const findings = [...root._reviewSession.findings].reverse().filter((finding) => {
    if (!filter) return true;
    if (filter === "active") return !inactiveReviewStatuses.has(finding.status);
    return finding.status === filter;
  });
  container.replaceChildren();
  if (!findings.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = root._reviewSession.findings.length
      ? "No findings match this status filter."
      : "No findings are recorded for this item.";
    container.append(empty);
    return;
  }
  findings.forEach((finding) => {
    const card = document.createElement("article");
    card.className = `review-finding review-severity-${finding.severity}`;
    card.dataset.status = finding.status;

    const header = document.createElement("div");
    header.className = "review-finding-header";
    const badges = document.createElement("div");
    badges.append(
      reviewBadge(finding.severity, `review-severity-${finding.severity}`),
      reviewBadge(finding.category, "review-category"),
      reviewBadge(finding.status, `review-status-${finding.status}`),
    );
    const identity = document.createElement("code");
    identity.textContent = finding.finding_id;
    header.append(badges, identity);
    card.append(header);

    const target = reviewTarget(finding.target);
    if (target) {
      const targetLine = document.createElement("p");
      targetLine.className = "review-finding-target";
      targetLine.textContent = target;
      card.append(targetLine);
    }
    card.append(reviewTextBlock("Observation", finding.observation));
    if (finding.expected) card.append(reviewTextBlock("Expected", finding.expected));
    const evidence = reviewReferences("Evidence", finding.evidence_refs);
    if (evidence) card.append(evidence);
    if (finding.resolution.summary) {
      card.append(reviewTextBlock("Resolution", finding.resolution.summary));
    }
    const resolutionEvidence = reviewReferences(
      "Resolution evidence",
      finding.resolution.evidence_refs,
    );
    if (resolutionEvidence) card.append(resolutionEvidence);
    const meta = document.createElement("p");
    meta.className = "review-finding-meta";
    meta.textContent = `${finding.reviewer} · updated ${finding.updated_at}`;
    card.append(meta, reviewResolutionForm(root, finding));
    container.append(card);
  });
}

function renderReviewSession(root, session) {
  root._reviewSession = session;
  const active = session.findings.filter(
    (finding) => !inactiveReviewStatuses.has(finding.status),
  ).length;
  const summary = root.querySelector("[data-review-mode-summary]");
  summary.replaceChildren();
  const sessionId = document.createElement("code");
  sessionId.textContent = session.session_id;
  const counts = document.createElement("span");
  counts.textContent = `${session.findings.length} findings · ${active} active · revision ${session.revision}`;
  summary.append(sessionId, counts);
  renderReviewFindings(root);
}

async function loadReviewSession(root) {
  try {
    renderReviewSession(root, await reviewRequest(root.dataset.sessionUrl));
  } catch (error) {
    reviewStatus(root, error.message, "save-error");
    const summary = root.querySelector("[data-review-mode-summary]");
    summary.textContent = "Review session unavailable.";
  }
}

function openReviewMode(root) {
  const body = root.querySelector("[data-review-mode-body]");
  const toggle = root.querySelector("[data-review-mode-toggle]");
  body.hidden = false;
  toggle.setAttribute("aria-expanded", "true");
  toggle.textContent = "Close Review Mode";
}

function setupReviewMode() {
  const root = document.querySelector("[data-review-mode-root]");
  if (!root) return;
  const body = root.querySelector("[data-review-mode-body]");
  const toggle = root.querySelector("[data-review-mode-toggle]");
  const form = root.querySelector("[data-review-finding-form]");
  const checkpoint = root.querySelector("[data-review-checkpoint]");
  const viewport = root.querySelector("[data-review-viewport]");

  toggle.addEventListener("click", () => {
    body.hidden = !body.hidden;
    toggle.setAttribute("aria-expanded", String(!body.hidden));
    toggle.textContent = body.hidden ? "Open Review Mode" : "Close Review Mode";
  });
  checkpoint.addEventListener("change", () => {
    const selected = checkpoint.selectedOptions[0];
    if (selected?.dataset.viewport) viewport.value = selected.dataset.viewport;
  });
  root.querySelector("[data-review-status-filter]").addEventListener(
    "change",
    () => root._reviewSession && renderReviewFindings(root),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    reviewStatus(root, "Saving finding…");
    const values = new FormData(form);
    try {
      const session = await reviewRequest(root.dataset.findingsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
        body: JSON.stringify({
          expected_revision: root._reviewSession.revision,
          finding: {
            severity: values.get("severity"),
            category: values.get("category"),
            target: {
              checkpoint: values.get("checkpoint") || null,
              viewport: values.get("viewport") || null,
              route: values.get("route") || null,
              role: values.get("role") || null,
              state: values.get("state") || null,
            },
            observation: values.get("observation"),
            expected: values.get("expected"),
            evidence_refs: lines(values.get("evidence_refs")),
          },
        }),
      });
      form.reset();
      renderReviewSession(root, session);
      reviewStatus(root, "Finding added.", "save-success");
    } catch (error) {
      if (error.status === 409) await loadReviewSession(root);
      reviewStatus(root, error.message, "save-error");
    } finally {
      submit.disabled = false;
    }
  });
  document.querySelectorAll("[data-review-current]").forEach((button) => {
    button.addEventListener("click", () => {
      const capture = button.closest("[data-capture]");
      openReviewMode(root);
      const option = [...checkpoint.options].find(
        (candidate) => candidate.value === capture.dataset.checkpoint &&
          candidate.dataset.viewport === capture.dataset.viewport,
      );
      if (option) option.selected = true;
      viewport.value = capture.dataset.viewport || "";
      root.scrollIntoView({ behavior: "smooth", block: "start" });
      form.elements.observation.focus({ preventScroll: true });
    });
  });
  if (new URLSearchParams(window.location.search).get("review") === "1") {
    openReviewMode(root);
  }
  loadReviewSession(root);
}

setupTaskAtlas();
setupReviewForm();
setupVisualReview();
setupComparePicker();
setupRouteExplorer();
setupJourneyReplay();
setupReviewMode();
