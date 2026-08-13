/* Lodging typeahead — the async-control shape used across this project:
   debounce, AbortController, a monotonic sequence guard so a slow earlier
   response can never overwrite a newer one, an aria-live status node, and an
   endpoint read from a data-* attribute rather than hardcoded here.

   The control is an enhancement. The field is a plain text input backed by a
   server-rendered <datalist>, so with scripting off the visitor still gets the
   seeded suggestions and can still type any hotel name and submit. */
(function () {
  "use strict";

  var field = document.querySelector("[data-typeahead]");
  if (!field) return;
  var endpoint = field.getAttribute("data-typeahead-endpoint");
  var list = document.getElementById(field.getAttribute("data-typeahead-list"));
  var status = document.querySelector("[data-typeahead-status]");
  if (!endpoint || !list || !status || typeof window.fetch !== "function") return;

  var MIN_QUERY = 2;
  var DEBOUNCE_MS = 120;
  var timer = null;
  var request = null;
  var sequence = 0;

  function render(results) {
    var items = Array.isArray(results) ? results.slice(0, 10) : [];
    list.replaceChildren();
    items.forEach(function (item) {
      if (!item || typeof item.name !== "string") return;
      var option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.address || "";
      list.appendChild(option);
    });
    list.removeAttribute("aria-busy");
    status.textContent = items.length
      ? items.length + " hotel suggestions available."
      : "No hotel suggestions for that name.";
  }

  function requestSuggestions() {
    var query = field.value.trim();
    if (query.length < MIN_QUERY) {
      if (request) request.abort();
      list.removeAttribute("aria-busy");
      status.textContent = "";
      return;
    }
    if (request) request.abort();
    request = new AbortController();
    var mine = ++sequence;
    var url = new URL(endpoint, window.location.origin);
    url.searchParams.set("q", query);
    list.setAttribute("aria-busy", "true");
    fetch(url, { headers: { Accept: "application/json" }, signal: request.signal })
      .then(function (response) {
        if (!response.ok) throw new Error("suggestions unavailable");
        return response.json();
      })
      .then(function (payload) {
        // Sequence guard: only the newest request may paint, and only while the
        // field still holds the text that request was made for.
        if (mine !== sequence || field.value.trim() !== query) return;
        render(payload.results);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        if (mine !== sequence) return;
        // The server-rendered options stay in place; say so rather than
        // silently leaving a stale count behind.
        list.removeAttribute("aria-busy");
        status.textContent = "Suggestions are unavailable right now.";
      });
  }

  function schedule() {
    if (timer !== null) window.clearTimeout(timer);
    timer = window.setTimeout(requestSuggestions, DEBOUNCE_MS);
  }

  field.addEventListener("input", schedule);
  field.addEventListener("focus", function () {
    if (field.value.trim().length >= MIN_QUERY) schedule();
  });
})();
