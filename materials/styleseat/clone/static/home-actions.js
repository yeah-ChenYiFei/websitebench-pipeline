/* Local navigation for captured StyleSeat marketing controls. */
(function () {
  "use strict";

  function navigate(path) {
    location.assign(path);
  }

  function bindButton(button, path, label) {
    if (!button || button.dataset.cloneActionBound) return;
    button.dataset.cloneActionBound = "1";
    if (label) button.setAttribute("aria-label", label);
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      navigate(path);
    }, true);
  }

  function bindBusinessButtons() {
    [
      document.querySelector('[data-testid="header-link-setup-my-business"]'),
      document.querySelector('[data-testid="home-hero-set-up-my-business-button"]')
    ].forEach(function (button) {
      bindButton(button, "/m/pro-signup", "Set up my business");
    });

    document.querySelectorAll("button").forEach(function (button) {
      if (!/^learn more$/i.test((button.textContent || "").trim())) return;
      var card = button.parentElement;
      while (card && card !== document.body) {
        var text = (card.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (text.indexOf("grow your business") >= 0) {
          return bindButton(button, "/join/grow-your-business", "Learn more about growing your business");
        }
        if (text.indexOf("manage your business") >= 0) {
          return bindButton(button, "/join/manage-your-business", "Learn more about managing your business");
        }
        if (text.indexOf("elevate your client experience") >= 0) {
          return bindButton(button, "/join/elevate-your-client-experience", "Learn more about client experience");
        }
        if (text.indexOf("set up your business") >= 0) {
          return bindButton(button, "/join/run-your-business", "Learn more about setting up your business");
        }
        card = card.parentElement;
      }
    });

    document.querySelectorAll("button").forEach(function (button) {
      var text = (button.textContent || "").replace(/\s+/g, " ").trim();
      if (/^(get started|start now|set up my business)$/i.test(text)) {
        bindButton(button, "/m/pro-signup", text || "Set up my business");
      }
    });
  }

  function cityRoute(locationValue) {
    var city = (locationValue || "").toLowerCase();
    var known = {
      "austin": "austin-tx", "baltimore": "baltimore-md", "atlanta": "atlanta-ga",
      "brooklyn": "brooklyn-ny", "charlotte": "charlotte-nc", "chicago": "chicago-il",
      "denver": "denver-co", "dallas": "dallas-tx", "honolulu": "honolulu-hi",
      "houston": "houston-tx", "las vegas": "las-vegas-nv", "miami": "miami-fl",
      "los angeles": "los-angeles-ca", "new york": "new-york-city-ny",
      "orlando": "orlando-fl", "philadelphia": "philadelphia-pa", "phoenix": "phoenix-az",
      "san antonio": "san-antonio-tx", "san diego": "san-diego-ca",
      "san francisco": "san-francisco-ca", "seattle": "seattle-wa", "tampa": "tampa-fl"
    };
    var slug = "new-york-city-ny";
    Object.keys(known).some(function (name) {
      if (city.indexOf(name) < 0) return false;
      slug = known[name];
      return true;
    });
    return "/m/search/" + slug + "/professionals";
  }

  function bindSearch() {
    var button = document.querySelector('[data-testid="search"]');
    if (!button) return;
    button.setAttribute("aria-label", "Search beauty professionals");
    button.dataset.cloneActionBound = "1";
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var query = document.querySelector('input[data-testid="query-input"]');
      var locationInput = document.querySelector('input[data-testid="location-input"]');
      var params = new URLSearchParams();
      if (query && query.value.trim()) params.set("q", query.value.trim());
      if (locationInput && locationInput.value.trim()) params.set("location", locationInput.value.trim());
      var suffix = params.toString();
      navigate(cityRoute(locationInput && locationInput.value) + (suffix ? "?" + suffix : ""));
    }, true);
  }

  function announce(message) {
    var status = document.querySelector("[data-clone-page-status]");
    if (!status) {
      status = document.createElement("aside");
      status.dataset.clonePageStatus = "1";
      status.setAttribute("role", "status");
      status.style.cssText = "position:sticky;top:0;z-index:30;padding:10px 20px;background:#fff3cd;color:#3d3200;font:14px/1.4 system-ui,sans-serif";
      document.body.insertBefore(status, document.body.firstChild);
    }
    status.textContent = message;
  }

  function bindSearchPageControls() {
    if (location.pathname.indexOf("/m/search/") !== 0) return;

    document.querySelectorAll('[data-testid^="filter-pill-"]').forEach(function (pill) {
      if (pill.dataset.cloneActionBound) return;
      pill.dataset.cloneActionBound = "1";
      pill.addEventListener("click", function (event) {
        event.preventDefault();
        var selected = pill.getAttribute("aria-selected") !== "true";
        pill.setAttribute("aria-selected", String(selected));
        pill.style.outline = selected ? "2px solid #3313b3" : "";
        announce((selected ? "Applied " : "Removed ") + (pill.getAttribute("aria-label") || pill.textContent.trim()) + " filter.");
      });
    });

    var date = document.querySelector('[data-testid="dateFilter"]');
    if (date && !date.dataset.cloneActionBound) {
      date.dataset.cloneActionBound = "1";
      date.addEventListener("click", function (event) {
        event.preventDefault();
        date.setAttribute("aria-pressed", date.getAttribute("aria-pressed") === "true" ? "false" : "true");
        announce(date.getAttribute("aria-pressed") === "true" ? "Availability filter applied." : "Availability filter cleared.");
      });
    }

    var sort = document.querySelector('[data-testid="search-sort-option-trigger-btn"]');
    var sortText = document.querySelector('[data-testid="searchSortText"]');
    if (sort && sortText && !sort.dataset.cloneActionBound) {
      sort.dataset.cloneActionBound = "1";
      sort.addEventListener("click", function (event) {
        event.preventDefault();
        sortText.textContent = /Best Match/.test(sortText.textContent) ? "Sort: Highest Rated" : "Sort: Best Match";
        announce(sortText.textContent + " applied to the archived result list.");
      });
    }
  }

  function explainFrozenSearch() {
    if (location.pathname.indexOf("/m/search/") !== 0 || !location.search) return;
    var params = new URLSearchParams(location.search);
    var notice = document.createElement("aside");
    notice.setAttribute("role", "status");
    notice.dataset.cloneSearchCriteria = "1";
    notice.style.cssText = "position:relative;z-index:5;padding:12px 20px;background:#f2efff;color:#24116d;font:14px/1.5 Poppins,system-ui,sans-serif";
    notice.textContent = "Offline results for " + (params.get("q") || "all services") +
      " near " + (params.get("location") || "the selected city") +
      ". The nearest captured city index is shown.";
    document.body.insertBefore(notice, document.body.firstChild);
  }

  function bindHomeAccordions() {
    document.querySelectorAll('[data-testid="accordion-section"]').forEach(function (section) {
      var trigger = section.querySelector('[tabindex="0"]');
      var box = section.querySelector('[data-testid="seo-accordion-box"]');
      if (!trigger || !box || trigger.dataset.cloneActionBound) return;
      trigger.dataset.cloneActionBound = "1";
      trigger.setAttribute("role", "button");
      trigger.setAttribute("aria-expanded", "false");
      box.style.height = "0px";
      box.style.overflow = "hidden";

      function toggle(event) {
        if (event) event.preventDefault();
        var opening = trigger.getAttribute("aria-expanded") !== "true";
        document.querySelectorAll('[data-testid="accordion-section"]').forEach(function (other) {
          var otherTrigger = other.querySelector('[tabindex="0"]');
          var otherBox = other.querySelector('[data-testid="seo-accordion-box"]');
          if (otherTrigger) otherTrigger.setAttribute("aria-expanded", "false");
          if (otherBox) {
            otherBox.style.height = "0px";
            otherBox.style.overflow = "hidden";
          }
        });
        trigger.setAttribute("aria-expanded", String(opening));
        box.style.height = opening ? "auto" : "0px";
        box.style.overflow = opening ? "visible" : "hidden";
      }

      trigger.addEventListener("click", toggle, true);
      trigger.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") toggle(event);
      });
    });
  }

  function boot() {
    bindBusinessButtons();
    bindSearch();
    bindSearchPageControls();
    bindHomeAccordions();
    explainFrozenSearch();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

