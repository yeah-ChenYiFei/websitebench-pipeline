/* Quote-funnel app for the aspca-pet-insurance offline clone.
 *
 * Vanilla JS, no frameworks, no remote loads. Renders captured view
 * fragments served from /quote/views/<name> and re-implements the
 * funnel behavior against the local JSON API only. All markup, classes and
 * validation copy come from the capture (2026-08-13.aspca-pet-insurance-r1);
 * business numbers (prices) always come from the API, never from this file.
 * Nothing entered by the user is persisted beyond sessionStorage quote state;
 * no credentials or provider payment data exist anywhere in this funnel.
 */
(function () {
  "use strict";

  /* Captured ng-pattern attrs (quote-start capture, verbatim). */
  var EMAIL_RE = /[a-z0-9A-Z._%+-]+@[a-z0-9A-Z.-]+\.[a-zA-Z]{2,4}$/;
  var PET_NAME_RE = /^[\sa-zA-Z0-9.-]*$/;
  var ZIP_RE = /^\d{5}$/;

  /* Pet name used in the captured rates scenario; replaced at render time
   * with the API quote's pet name (mechanical parameterization). */
  var CAPTURED_PET_NAME = "Willow";

  var ROUTES = {
    "#/start": { view: "start", title: "Let's get started!" },
    "#/plans": { view: "rates", title: "Select A Plan", guard: true },
    "#/checkout": { view: "checkout", title: "Complete Your Enrollment",
      guard: true },
    "#/quote-search": { view: "resume", title: "Find a Previous Quote." },
    "#/add-a-pet": { view: "add-a-pet", title: "Add a Pet", guard: true }
  };

  var root = document.getElementById("app-root");
  var viewCache = {};
  var lastStartValues = null;
  var rateRequestSequence = 0;

  function waitForViewResources() {
    var resources = root.querySelectorAll("img, link[rel='stylesheet']");
    var pending = [];
    Array.prototype.forEach.call(resources, function (resource) {
      pending.push(new Promise(function (resolve) {
        var done = false;
        function settle() {
          if (!done) { done = true; resolve(); }
        }
        resource.addEventListener("load", settle, { once: true });
        resource.addEventListener("error", settle, { once: true });
        var ready = resource.tagName === "IMG" ? resource.complete : resource.sheet;
        if (ready) { settle(); }
        else { setTimeout(settle, 2000); }
      }));
    });
    return Promise.all(pending)
      .then(function () {
        return document.fonts ? document.fonts.ready : undefined;
      })
      .then(function () {
        return new Promise(function (resolve) {
          requestAnimationFrame(function () { requestAnimationFrame(resolve); });
        });
      })
      .then(function () {
        setTimeout(function () { root.setAttribute("data-view-ready", "true"); }, 0);
      });
  }

  /* ------------------------------------------------------------------ */
  /* State (sessionStorage; quote data only — never credentials).        */
  function getQuote() {
    try { return JSON.parse(sessionStorage.getItem("aspca.quote")); }
    catch (e) { return null; }
  }
  function setQuote(quote) {
    sessionStorage.setItem("aspca.quote", JSON.stringify(quote));
    if (quote && quote.quote_id) {
      sessionStorage.setItem("aspca.quote_id", String(quote.quote_id));
    }
  }
  function getQuoteId() { return sessionStorage.getItem("aspca.quote_id"); }
  function getSelection() {
    try { return JSON.parse(sessionStorage.getItem("aspca.selection")); }
    catch (e) { return null; }
  }
  function setSelection(sel) {
    sessionStorage.setItem("aspca.selection", JSON.stringify(sel));
  }

  /* ------------------------------------------------------------------ */
  /* Same-origin helpers.                                                */
  function api(method, url, body) {
    var opts = { method: method,
      headers: { "Accept": "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return {}; })
        .then(function (data) { return { status: res.status, data: data }; });
    });
  }

  function fetchView(name) {
    if (viewCache[name]) { return Promise.resolve(viewCache[name]); }
    return fetch("/quote/views/" + name).then(function (res) {
      if (!res.ok) { throw new Error("view " + name + ": " + res.status); }
      return res.text();
    }).then(function (text) {
      /* The frozen fragments contain a source tag that labels a Typekit JS
       * loader as CSS. The loader is unnecessary offline and strict browsers
       * reject it, so omit that inert tag at render time. */
      text = text.replace(
        /<link\b[^>]*href=["'][^"']*\/ezj2kxi\.js["'][^>]*>/gi, "");
      viewCache[name] = text;
      return text;
    });
  }

  function render(name, onRendered) {
    return fetchView(name).then(function (html) {
      root.removeAttribute("data-view-ready");
      root.innerHTML = html;
      root.setAttribute("data-view", name);
      root.removeAttribute("data-view-loading");
      window.scrollTo(0, 0);
      /* Bind behavior as soon as controls are visible. Images and fonts may
       * continue settling before the view is marked visually ready. */
      if (onRendered) { onRendered(); }
      return waitForViewResources();
    });
  }

  function funnelForm() {
    return root.querySelector('form[name="form"]');
  }

  function money(n) { return "$" + Number(n).toFixed(2); }

  /* Neutral offline-clone failure note (backend unreachable). Truthful,
   * never styled as a source-brand message. */
  function apiFailure(err) {
    var note = document.createElement("p");
    note.className = "formErrors";
    note.setAttribute("role", "alert");
    note.textContent = "Request failed (offline clone backend unavailable).";
    var form = funnelForm();
    if (form) { form.insertBefore(note, form.firstChild); }
    if (window.console) { console.error(err); }
  }

  /* ------------------------------------------------------------------ */
  /* #/start — captured form, captured validation states.                */

  var START_ERROR_IDS = {
    name: "expPetName", zip: "expZipCode", age: "ageError",
    gender: "expSelectPetSpecies", breed: "breedError", email: "expEmail"
  };
  /* Captured errorSummary list-item prefixes, keyed like the errors. */
  var START_SUMMARY_PREFIX = {
    species: null, name: "Pet's Name:", zip: "Zip Code:", age: "Age:",
    gender: "Pet Gender:", breed: "Breed:", email: "Email Address:"
  };

  function radioValue(form, name) {
    var checked = form.querySelector('input[name="' + name + '"]:checked');
    return checked ? checked.value : "";
  }

  function selectedAgeLabel(sel) {
    if (!sel || sel.selectedIndex < 0) { return ""; }
    var opt = sel.options[sel.selectedIndex];
    if (!opt || opt.value === "") { return ""; }
    return opt.getAttribute("label") || opt.textContent.trim();
  }

  function collectStart(form) {
    return {
      species: radioValue(form, "petSpecies"),
      name: (form.elements.petsName ? form.elements.petsName.value : "").trim(),
      zip: (form.elements.zipcode ? form.elements.zipcode.value : "").trim(),
      age: selectedAgeLabel(form.elements.choAge),
      gender: radioValue(form, "petSex"),
      breed: (form.elements.inputBreedList
        ? form.elements.inputBreedList.value : "").trim(),
      email: (form.elements.emailAddress
        ? form.elements.emailAddress.value : "").trim()
    };
  }

  function applyStartValues(form, values) {
    if (!values) { return; }
    if (values.species) {
      var sp = form.querySelector(
        'input[name="petSpecies"][value="' + values.species + '"]');
      if (sp) { sp.checked = true; }
    }
    if (form.elements.petsName) { form.elements.petsName.value = values.name; }
    if (form.elements.zipcode) { form.elements.zipcode.value = values.zip; }
    if (form.elements.choAge && values.age) {
      var ages = form.elements.choAge.options;
      for (var i = 0; i < ages.length; i += 1) {
        var label = ages[i].getAttribute("label") || ages[i].textContent.trim();
        if (label === values.age) { form.elements.choAge.selectedIndex = i; }
      }
    }
    if (values.gender) {
      var g = form.querySelector(
        'input[name="petSex"][value="' + values.gender + '"]');
      if (g) { g.checked = true; }
    }
    if (form.elements.inputBreedList) {
      form.elements.inputBreedList.value = values.breed;
    }
    if (form.elements.emailAddress) {
      form.elements.emailAddress.value = values.email;
    }
  }

  function validateStart(values) {
    var errors = {};
    if (!values.species) { errors.species = true; }
    if (!values.name || !PET_NAME_RE.test(values.name)) { errors.name = true; }
    if (!ZIP_RE.test(values.zip)) { errors.zip = true; }
    if (!values.age) { errors.age = true; }
    if (!values.gender) { errors.gender = true; }
    if (!values.breed) { errors.breed = true; }
    if (!EMAIL_RE.test(values.email)) { errors.email = true; }
    return errors;
  }

  /* Render the captured empty-submit validation state, then prune the
   * error nodes for fields that are actually valid and overlay any
   * server-provided messages into the captured markup. */
  function showStartValidation(values, errors, serverMessages) {
    render("start-validation").then(function () {
      var form = funnelForm();
      applyStartValues(form, values);
      Object.keys(START_ERROR_IDS).forEach(function (field) {
        var el = document.getElementById(START_ERROR_IDS[field]);
        var msg = serverMessages && serverMessages[field];
        if (!errors[field] && !msg) {
          if (el && el.parentNode) { el.parentNode.removeChild(el); }
          removeSummaryItem(field);
        } else if (msg && el) {
          el.textContent = msg;
          updateSummaryItem(field, msg);
        }
      });
      var summary = document.getElementById("errorSummary");
      if (summary && !root.querySelector(".errorSummary_listItem")) {
        var wrap = summary.parentNode;
        if (wrap && wrap.parentNode) { wrap.parentNode.removeChild(wrap); }
      } else if (summary) {
        summary.focus();
      }
      wireStart();
    });
  }

  function summaryItemFor(field) {
    var prefix = START_SUMMARY_PREFIX[field];
    if (!prefix) { return null; }
    var items = root.querySelectorAll(".errorSummary_listItem");
    for (var i = 0; i < items.length; i += 1) {
      if (items[i].textContent.trim().indexOf(prefix) === 0) {
        return items[i];
      }
    }
    return null;
  }
  function removeSummaryItem(field) {
    var item = summaryItemFor(field);
    if (item && item.parentNode) { item.parentNode.removeChild(item); }
  }
  function updateSummaryItem(field, msg) {
    var item = summaryItemFor(field);
    var prefix = START_SUMMARY_PREFIX[field];
    if (item && prefix) { item.textContent = prefix + " " + msg; }
  }

  /* Captured ineligible state: the zip error message template is
   * "<zip> is not a valid zip code." (ng-bind valueIsNotAValidZipcode). */
  function showIneligible(values, serverMessage) {
    render("ineligible").then(function () {
      var form = funnelForm();
      applyStartValues(form, values);
      var msg = root.querySelector('p[ng-bind*="valueIsNotAValidZipcode"]');
      if (msg) {
        if (serverMessage) {
          msg.textContent = serverMessage;
        } else if (values && values.zip) {
          msg.textContent =
            msg.textContent.replace(/^\S+/, values.zip);
        }
      }
      wireStart();
    });
  }

  function submitStart(event) {
    event.preventDefault();
    var form = funnelForm();
    var values = collectStart(form);
    lastStartValues = values;
    var errors = validateStart(values);
    if (Object.keys(errors).length) {
      showStartValidation(values, errors, null);
      return;
    }
    api("POST", "/api/quotes", values).then(function (res) {
      if (res.status === 422 && res.data && res.data.eligible === false) {
        showIneligible(values,
          res.data.errors && res.data.errors.zip ? res.data.errors.zip : null);
      } else if (res.status === 422 && res.data && res.data.errors) {
        showStartValidation(values, {}, res.data.errors);
      } else if (res.status === 201 || res.status === 200) {
        if (res.data.eligible === false) {
          showIneligible(values, res.data.message || null);
          return;
        }
        setQuote(res.data);
        sessionStorage.removeItem("aspca.selection");
        window.location.hash = "#/plans";
      } else {
        apiFailure(new Error("quotes " + res.status));
      }
    }).catch(apiFailure);
  }

  function wireStart() {
    var form = funnelForm();
    if (form) { form.addEventListener("submit", submitStart); }
  }

  function initStart() {
    if (lastStartValues) {
      var form = funnelForm();
      if (form) { applyStartValues(form, lastStartValues); }
    }
    wireStart();
  }

  /* ------------------------------------------------------------------ */
  /* #/plans — captured rates view; prices always injected from the API. */

  var TIER_KEYS = ["essential", "plus", "elite"];

  function normalizeTierData(rates) {
    var out = {};
    if (!rates) { return out; }
    var list = Array.isArray(rates) ? rates : rates.tiers;
    if (Array.isArray(list)) {
      /* The API returns tiers in the same low/middle/high order as the
       * captured Value/Popular/High Coverage cards. */
      list.forEach(function (tier, index) {
        var key = tier.tier || tier.name || TIER_KEYS[index];
        if (key) { out[String(key).toLowerCase()] = tier; }
      });
      return out;
    }
    Object.keys(rates).forEach(function (key) {
      var v = rates[key];
      if (v && typeof v === "object" && v.monthly !== undefined) {
        out[key.toLowerCase()] = v;
      }
    });
    return out;
  }

  function normalizeRates(rates) {
    var out = {};
    var tiers = normalizeTierData(rates);
    Object.keys(tiers).forEach(function (key) {
      out[key] = tiers[key].monthly;
    });
    return out;
  }

  function swapPetName(newName) {
    if (!newName || newName === CAPTURED_PET_NAME) { return; }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node.nodeValue.indexOf(CAPTURED_PET_NAME) !== -1) {
        node.nodeValue =
          node.nodeValue.split(CAPTURED_PET_NAME).join(newName);
      }
    }
    var labeled = root.querySelectorAll("[aria-label]");
    for (var i = 0; i < labeled.length; i += 1) {
      var val = labeled[i].getAttribute("aria-label");
      if (val.indexOf(CAPTURED_PET_NAME) !== -1) {
        labeled[i].setAttribute(
          "aria-label", val.split(CAPTURED_PET_NAME).join(newName));
      }
    }
  }

  function setPriceText(el, monthly) {
    if (!el) { return; }
    /* Preserve the sr-only child; replace only the trailing text node. */
    var last = el.lastChild;
    var text = money(monthly) + "/mo";
    if (last && last.nodeType === 3) { last.nodeValue = text; }
    else { el.appendChild(document.createTextNode(text)); }
  }

  function setTierPrices(rates) {
    var options = root.querySelectorAll("li[data-tier]");
    for (var i = 0; i < options.length; i += 1) {
      var tier = options[i].getAttribute("data-tier");
      if (rates[tier] !== undefined) {
        setPriceText(options[i].querySelector(
          ".eb-tier-selector__option-price"), rates[tier]);
      }
    }
  }

  function updatePricebar(monthly) {
    var parts = Number(monthly).toFixed(2).split(".");
    var dollars = root.querySelectorAll(
      ".priceSummary_priceMonthly--dollar, .priceTotal_text--dollar");
    var cents = root.querySelectorAll(
      ".priceSummary_priceMonthly--cents, .priceTotal_text--cents");
    var i;
    for (i = 0; i < dollars.length; i += 1) {
      dollars[i].textContent = "$" + parts[0];
    }
    for (i = 0; i < cents.length; i += 1) {
      cents[i].textContent = "." + parts[1];
    }
  }

  /* Bootstrap-style collapse toggling with the exact captured classes. */
  function wireCollapse() {
    var buttons = root.querySelectorAll('[data-toggle="collapse"]');
    Array.prototype.forEach.call(buttons, function (btn) {
      btn.addEventListener("click", function (event) {
        event.preventDefault();
        var target = btn.getAttribute("data-target");
        if (!target) { return; }
        /* Some captured panel ids contain a curly apostrophe; resolve by
         * raw id, never through the CSS selector parser. */
        var panel = document.getElementById(target.slice(1));
        if (!panel) { return; }
        var open = panel.classList.contains("in");
        if (open) {
          panel.classList.remove("in");
          panel.classList.add("collapse");
          panel.style.height = "";
          btn.classList.add("collapsed");
          btn.setAttribute("aria-expanded", "false");
        } else {
          panel.classList.remove("collapse");
          panel.classList.add("in");
          panel.style.height = "auto";
          btn.classList.remove("collapsed");
          btn.setAttribute("aria-expanded", "true");
        }
      });
    });
  }

  function customChoices() {
    var groups = { annualDeductiblel2: null, reimbursementPercentl2: null,
      annualLimitl2: null };
    Object.keys(groups).forEach(function (name) {
      var checked = root.querySelector(
        'input[name="' + name + '"]:checked');
      groups[name] = checked ? checked.value : null;
    });
    if (!groups.annualDeductiblel2 || !groups.reimbursementPercentl2 ||
        !groups.annualLimitl2) {
      return null;
    }
    var limitRaw = groups.annualLimitl2.replace("Limit", "");
    return {
      deductible: parseInt(
        groups.annualDeductiblel2.replace("Deductible", ""), 10),
      reimbursement: 100 - parseInt(
        groups.reimbursementPercentl2.replace("Copay", ""), 10),
      limit: limitRaw === "Unlimited" ? "unlimited" : parseInt(limitRaw, 10)
    };
  }

  function postRate(sel, done) {
    var requestId = ++rateRequestSequence;
    root.setAttribute("data-rate-pending", "true");
    return api("POST", "/api/quotes/" + getQuoteId() + "/rate", {
      limit: sel.limit,
      deductible: sel.deductible,
      reimbursement: sel.reimbursement,
      preventive: sel.preventive || null
    }).then(function (res) {
      if (requestId !== rateRequestSequence) { return; }
      if (res.status >= 200 && res.status < 300) {
        var oldError = document.getElementById("rate-recalculation-error");
        if (oldError && oldError.parentNode) { oldError.parentNode.removeChild(oldError); }
        done(res.data);
      } else {
        var note = document.getElementById("rate-recalculation-error");
        if (!note) {
          note = document.createElement("p");
          note.id = "rate-recalculation-error";
          note.className = "formErrors";
          note.setAttribute("role", "alert");
          var controls = document.getElementById("plan-comparison-controls");
          (controls || root).insertBefore(note, (controls || root).firstChild);
        }
        note.textContent = "Rate recalculation could not use that option. " +
          "Your previous selection is preserved; choose another option to retry.";
      }
    }).catch(function (error) {
      if (requestId === rateRequestSequence) { apiFailure(error); }
    }).then(function () {
      if (requestId === rateRequestSequence) {
        root.setAttribute("data-rate-pending", "false");
      }
    });
  }

  function refreshCustomRate(preventive) {
    var choices = customChoices();
    if (!choices) { return; }
    var sel = { type: "custom", limit: choices.limit,
      deductible: choices.deductible, reimbursement: choices.reimbursement,
      preventive: preventive };
    postRate(sel, function (data) {
      sel.monthly = data.monthly;
      sel.preventive_monthly = data.preventive_monthly;
      sel.total_monthly = data.total_monthly;
      setSelection(sel);
      setPriceText(document.getElementById("dtc-price-complete"),
        data.monthly);
      updatePricebar(data.monthly);
      if (data.preventive_monthly) {
        updatePreventivePrice(preventive, data.preventive_monthly);
      }
    });
  }

  function preventiveElements(key) {
    var all = root.querySelectorAll("[ng-click]");
    var found = { add: null, remove: null };
    Array.prototype.forEach.call(all, function (el) {
      var expr = el.getAttribute("ng-click");
      if (expr.indexOf("togglePreventiveCareSelection") === -1) { return; }
      var cls = el.getAttribute("ng-class") || "";
      if (expr.indexOf("'" + key + "'") !== -1) { found.add = el; }
      else if (expr.indexOf("'none'") !== -1 &&
          cls.indexOf("'" + key + "'") !== -1) { found.remove = el; }
    });
    return found;
  }

  function updatePreventivePrice(key, monthly) {
    if (!key) { return; }
    var els = preventiveElements(key);
    var anchor = els.add || els.remove;
    if (!anchor) { return; }
    var panel = anchor.closest(".panel_footer") || anchor.parentNode;
    var price = panel && panel.querySelector(
      ".opcpriceSummary_priceMonthly");
    if (price) { price.textContent = money(monthly) + "/mo"; }
  }

  function wirePreventive() {
    ["basic", "prime"].forEach(function (key) {
      var els = preventiveElements(key);
      if (els.add) {
        els.add.addEventListener("click", function (event) {
          event.preventDefault();
          togglePreventive(key);
        });
      }
      if (els.remove) {
        els.remove.addEventListener("click", function (event) {
          event.preventDefault();
          togglePreventive(null);
        });
      }
    });
  }

  function togglePreventive(key) {
    var sel = getSelection() || {};
    sel.preventive = key;
    setSelection(sel);
    ["basic", "prime"].forEach(function (k) {
      var els = preventiveElements(k);
      if (els.add) { els.add.classList.toggle("button-hidden", key === k); }
      if (els.remove) {
        els.remove.classList.toggle("button-hidden", key !== k);
      }
    });
    if (sel.type === "custom") { refreshCustomRate(key); }
  }

  function setContinueDisabled(disabled) {
    var button = root.querySelector('[aria-label="Continue to next step"]');
    if (button) { button.disabled = disabled; }
  }

  function wireContinue() {
    var button = root.querySelector('[aria-label="Continue to next step"]');
    if (!button) { return; }
    button.type = "button";
    button.addEventListener("click", function (event) {
      event.preventDefault();
      if (root.getAttribute("data-rate-pending") === "true") { return; }
      window.location.hash = "#/checkout";
    });
  }

  function updateTierSelectionUi(options, selectedTier) {
    var group = root.querySelector('.eb-tier-selector__list[role="radiogroup"]');
    Array.prototype.forEach.call(options, function (option) {
      var mine = option.getAttribute("data-tier") === selectedTier;
      option.setAttribute("aria-checked", mine ? "true" : "false");
      option.setAttribute("tabindex", mine ? "0" : "-1");
      option.classList.toggle("eb-tier-selector__option--selected", mine);
      if (mine && group) {
        group.setAttribute("aria-activedescendant", option.id);
      }
      var button = option.querySelector(".eb-tier-selector__option-button");
      if (!button) { return; }
      var heading = option.querySelector(".eb-tier-selector__option-name");
      var name = heading ? heading.textContent.trim() : selectedTier;
      button.setAttribute("aria-label",
        mine ? name + " tier selected" : "Select " + name + " tier");
      var status = button.querySelector("span[aria-hidden='true']");
      if (status) { status.textContent = mine ? "Plan Selected" : "Select Plan"; }
      var check = button.querySelector(".eb-tier-selector__option-button-check");
      if (check) { check.classList.toggle("ng-hide", !mine); }
    });
  }

  function wireTiers(tiers) {
    var options = root.querySelectorAll('li[data-tier][role="radio"]');
    function select(option, event) {
      if (event) { event.preventDefault(); }
      var tier = option.getAttribute("data-tier");
      var plan = tiers[tier];
      if (!plan) { return; }
      updateTierSelectionUi(options, tier);
      var previous = getSelection() || {};
      var request = {
        type: "tier",
        tier: tier,
        limit: plan.annual_limit,
        deductible: plan.deductible,
        reimbursement: plan.reimbursement,
        preventive: previous.preventive || null
      };
      var committed = false;
      setContinueDisabled(true);
      postRate(request, function (data) {
        committed = true;
        request.monthly = data.monthly;
        request.preventive_monthly = data.preventive_monthly;
        request.total_monthly = data.total_monthly;
        setSelection(request);
        updatePricebar(data.total_monthly || data.monthly);
      }).then(function () {
        if (!committed) {
          var preserved = getSelection() || previous;
          if (preserved.type === "tier" && preserved.tier) {
            updateTierSelectionUi(options, preserved.tier);
          }
        }
        setContinueDisabled(false);
      });
    }
    Array.prototype.forEach.call(options, function (option) {
      var button = option.querySelector(".eb-tier-selector__option-button");
      if (button) { button.type = "button"; }
      option.addEventListener("click", function (event) {
        select(option, event);
      });
      option.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          select(option, event);
          return;
        }
        var previous = event.key === "ArrowLeft" || event.key === "ArrowUp";
        var next = event.key === "ArrowRight" || event.key === "ArrowDown";
        if (!previous && !next && event.key !== "Home" && event.key !== "End") {
          return;
        }
        event.preventDefault();
        var currentIndex = Array.prototype.indexOf.call(options, option);
        var targetIndex = event.key === "Home" ? 0
          : event.key === "End" ? options.length - 1
          : (currentIndex + (previous ? -1 : 1) + options.length) % options.length;
        var target = options[targetIndex];
        target.focus();
        select(target, event);
      });
    });
  }

  function wireCustomRadios() {
    ["annualDeductiblel2", "reimbursementPercentl2", "annualLimitl2"]
      .forEach(function (name) {
        var radios = root.querySelectorAll('input[name="' + name + '"]');
        Array.prototype.forEach.call(radios, function (radio) {
          radio.addEventListener("change", function () {
            var sel = getSelection() || {};
            refreshCustomRate(sel.preventive || null);
          });
        });
      });
  }

  function buildPlanComparison(tiers) {
    var list = root.querySelector('.eb-tier-selector__list[role="radiogroup"]');
    if (!list || document.getElementById("plan-comparison-controls")) { return; }
    var controls = document.createElement("section");
    controls.id = "plan-comparison-controls";
    controls.setAttribute("aria-label", "Sort and compare plans");
    controls.style.cssText = "margin:16px auto;padding:16px;max-width:980px;border:1px solid #ccc;background:#fff";
    controls.innerHTML = '<label for="plan-sort"><strong>Sort plans</strong></label> ' +
      '<select id="plan-sort"><option value="source">Recommended order</option>' +
      '<option value="price-low">Monthly price: low to high</option>' +
      '<option value="price-high">Monthly price: high to low</option></select> ' +
      '<button id="save-quote" type="button">Save Quote</button> ' +
      '<span id="save-quote-status" role="status"></span>' +
      '<fieldset id="plan-compare"><legend>Compare plans</legend></fieldset>' +
      '<div id="plan-compare-summary" role="status">Select two or more plans to compare.</div>';
    list.parentNode.insertBefore(controls, list);
    var fieldset = controls.querySelector("#plan-compare");
    var savedCompare;
    try { savedCompare = JSON.parse(sessionStorage.getItem("aspca.plan_compare")) || []; }
    catch (error) { savedCompare = []; }
    Array.prototype.forEach.call(list.querySelectorAll("li[data-tier]"), function (item) {
      var tier = item.getAttribute("data-tier");
      var heading = item.querySelector(".eb-tier-selector__option-name");
      var name = heading ? heading.textContent.trim() : tier;
      var label = document.createElement("label");
      label.style.marginRight = "18px";
      label.innerHTML = '<input type="checkbox" name="compareTier" value="' + tier + '"' +
        (savedCompare.indexOf(tier) !== -1 ? " checked" : "") + '> ' + name;
      fieldset.appendChild(label);
    });
    function updateCompare() {
      var selected = Array.prototype.map.call(
        controls.querySelectorAll('input[name="compareTier"]:checked'),
        function (input) { return input.value; });
      sessionStorage.setItem("aspca.plan_compare", JSON.stringify(selected));
      var summary = controls.querySelector("#plan-compare-summary");
      if (selected.length < 2) {
        summary.textContent = "Select two or more plans to compare.";
      } else {
        summary.innerHTML = selected.map(function (tier) {
          var plan = tiers[tier];
          return '<strong>' + tier + '</strong>: $' + Number(plan.monthly).toFixed(2) +
            '/month, $' + Number(plan.annual_limit).toLocaleString("en-US") +
            ' limit, $' + plan.deductible + ' deductible, ' +
            plan.reimbursement + '% reimbursement';
        }).join("<br>");
      }
    }
    fieldset.addEventListener("change", updateCompare);
    updateCompare();
    var sort = controls.querySelector("#plan-sort");
    sort.value = sessionStorage.getItem("aspca.plan_sort") || "source";
    function applySort() {
      var items = Array.prototype.slice.call(list.querySelectorAll("li[data-tier]"));
      if (sort.value !== "source") {
        items.sort(function (left, right) {
          var delta = Number(tiers[left.getAttribute("data-tier")].monthly) -
            Number(tiers[right.getAttribute("data-tier")].monthly);
          return sort.value === "price-low" ? delta : -delta;
        });
      } else {
        items.sort(function (left, right) {
          return TIER_KEYS.indexOf(left.getAttribute("data-tier")) -
            TIER_KEYS.indexOf(right.getAttribute("data-tier"));
        });
      }
      items.forEach(function (item) { list.appendChild(item); });
      sessionStorage.setItem("aspca.plan_sort", sort.value);
      list.setAttribute("data-sort", sort.value);
    }
    sort.addEventListener("change", applySort);
    applySort();
    controls.querySelector("#save-quote").addEventListener("click", function () {
      var quote = getQuote() || {};
      sessionStorage.setItem("aspca.quote_saved", "true");
      controls.querySelector("#save-quote-status").textContent =
        "Quote " + (quote.quote_id || "") +
        " saved. Resume it with your email and ZIP.";
    });
    if (sessionStorage.getItem("aspca.quote_saved") === "true") {
      var quote = getQuote() || {};
      controls.querySelector("#save-quote-status").textContent =
        "Saved quote " + (quote.quote_id || "") + ".";
    }
  }

  function initPlans() {
    var quote = getQuote() || {};
    if (quote.pet && quote.pet.name) { swapPetName(quote.pet.name); }
    var tiers = normalizeTierData(quote.rates);
    var rates = normalizeRates(quote.rates);
    setTierPrices(rates);
    buildPlanComparison(tiers);
    var sel = getSelection();
    if (sel && sel.monthly !== undefined) {
      updatePricebar(sel.monthly);
      if (sel.type === "tier" && sel.tier) {
        var options = root.querySelectorAll("li[data-tier]");
        updateTierSelectionUi(options, sel.tier);
      }
      if (sel.preventive) {
        ["basic", "prime"].forEach(function (k) {
          var els = preventiveElements(k);
          if (els.add) {
            els.add.classList.toggle("button-hidden", sel.preventive === k);
          }
          if (els.remove) {
            els.remove.classList.toggle(
              "button-hidden", sel.preventive !== k);
          }
        });
      }
    } else {
      /* Default to the tier the capture shows as selected. */
      var selected = root.querySelector(
        "li[data-tier].eb-tier-selector__option--selected");
      if (selected) {
        var tier = selected.getAttribute("data-tier");
        if (rates[tier] !== undefined) {
          var plan = tiers[tier];
          setSelection({ type: "tier", tier: tier, monthly: rates[tier],
            limit: plan.annual_limit, deductible: plan.deductible,
            reimbursement: plan.reimbursement, preventive: null,
            preventive_monthly: "0.00", total_monthly: rates[tier] });
          updateTierSelectionUi(root.querySelectorAll("li[data-tier]"), tier);
          updatePricebar(rates[tier]);
        }
      }
    }
    root.setAttribute("data-rate-pending", "false");
    wireTiers(tiers);
    wireContinue();
    wireCollapse();
    wireCustomRadios();
    wirePreventive();
  }

  /* ------------------------------------------------------------------ */
  /* #/checkout — captured form + explicitly clone-local sandbox control. */

  var CHECKOUT_REQUIRED = ["firstName", "lastName", "address1", "city",
    "stateSelect", "zipcode", "phone", "email"];

  function setCheckoutCell(labelId, value) {
    var cell = root.querySelector('td[aria-labelledby="' + labelId + '"]');
    var target = cell && (cell.querySelector(".ng-binding") || cell);
    if (target) { target.textContent = value; }
  }

  function setPriceWithSuffix(id, value) {
    var target = document.getElementById(id);
    if (!target) { return; }
    var first = target.firstChild;
    if (first && first.nodeType === 3) { first.nodeValue = money(value); }
  }

  function updateCheckoutSummary(selection) {
    var limit = selection.limit || selection.annual_limit;
    var baseMonthly = Number(selection.monthly || 0);
    var preventiveMonthly = Number(selection.preventive_monthly || 0);
    var totalMonthly = Number(selection.total_monthly ||
      (baseMonthly + preventiveMonthly));
    if (limit) {
      setCheckoutCell("annualLimit-label-0",
        "$" + Number(limit).toLocaleString("en-US"));
    }
    if (selection.deductible) {
      setCheckoutCell("deductible-label-0", money(selection.deductible)
        .replace(".00", ""));
    }
    if (selection.reimbursement) {
      setCheckoutCell("reimbursement-label-0",
        String(selection.reimbursement) + "%");
    }
    setCheckoutCell("premiumCost-label-0", money(baseMonthly));
    setCheckoutCell("totalCost-label-0", money(totalMonthly));
    setPriceWithSuffix("monthly-price", totalMonthly);
    setPriceWithSuffix("annually-price", totalMonthly * 12);
    var today = root.querySelector("#payment-summary-table tfoot td .ng-binding");
    if (today) { today.textContent = money(totalMonthly); }
    var fee = root.querySelector("#payment-summary-table .payment__fee-label");
    if (fee && fee.closest("tr")) { fee.closest("tr").hidden = true; }
    var pricebar = root.querySelector(".pricebar_btn");
    if (pricebar) { pricebar.textContent = money(totalMonthly); }
    var schedule = document.getElementById("payment-schedule-text");
    if (schedule) {
      schedule.textContent = "Today you will be charged " +
        money(totalMonthly) + ". Your account will be charged " +
        money(totalMonthly) +
        " on the 14th of each month or the following business day.";
    }

    var hasPreventive = !!selection.preventive;
    var preventiveLabel = document.getElementById("preventivePlan-label-0");
    if (preventiveLabel) {
      preventiveLabel.textContent = hasPreventive
        ? (selection.preventive === "prime"
          ? "Prime Preventive Care" : "Basic Preventive Care")
        : "No Preventive Care";
    }
    setCheckoutCell("preventivePlan-label-0",
      hasPreventive ? "Added" : "Not added");
    var effective = document.getElementById("preventiveEffective-label-0");
    if (effective && effective.closest("tr")) {
      effective.closest("tr").style.display = hasPreventive ? "" : "none";
    }
    var preventiveCost = document.getElementById("preventiveCost-label-0");
    if (preventiveCost && preventiveCost.closest("tr")) {
      preventiveCost.closest("tr").style.display = hasPreventive ? "" : "none";
      setCheckoutCell("preventiveCost-label-0", money(preventiveMonthly));
    }
    var preventiveEdit = root.querySelector(
      'button[aria-label^="Edit preventive care for"]');
    if (preventiveEdit) {
      preventiveEdit.style.display = hasPreventive ? "" : "none";
    }
    updatePricebar(totalMonthly);
  }

  function hydrateCheckout(form) {
    var quote = getQuote() || {};
    var pet = quote.pet || (quote.pets && quote.pets[0]);
    if (pet && pet.name) { swapPetName(pet.name); }
    if (form.elements.stateSelect && quote.state) {
      form.elements.stateSelect.value = quote.state;
    }
    if (form.elements.zipcode && quote.zip) {
      form.elements.zipcode.value = quote.zip;
    }
    if (form.elements.email && quote.email) {
      form.elements.email.value = quote.email;
    }
    var selection = getSelection() || (pet && pet.selection);
    if (selection && selection.monthly !== undefined) {
      updateCheckoutSummary(selection);
    }
  }

  /* Captured banner markup (quote-start-validation capture). */
  function buildBanner() {
    var banner = document.createElement("p");
    banner.className = "errorSummary center";
    banner.id = "errorSummary";
    banner.setAttribute("tabindex", "-1");
    banner.textContent = "Error: Please correct the following issue(s).";
    return banner;
  }

  function inlineError(text) {
    var p = document.createElement("p");
    p.className = "formErrors";
    p.setAttribute("role", "alert");
    p.textContent = text;
    return p;
  }

  function clearInsertedErrors(form) {
    Array.prototype.forEach.call(
      form.querySelectorAll("p.formErrors, p.errorSummary"),
      function (el) { el.parentNode.removeChild(el); });
    Array.prototype.forEach.call(form.elements, function (el) {
      el.classList.remove("ng-invalid", "ng-touched");
      el.removeAttribute("aria-invalid");
    });
  }

  function markInvalid(control, message) {
    control.classList.add("ng-invalid", "ng-touched");
    control.setAttribute("aria-invalid", "true");
    if (message) {
      var target = control.closest("div") || control.parentNode;
      target.appendChild(inlineError(message));
    }
  }

  function buildLocalPaymentSimulation(form) {
    if (form.querySelector("#localPaymentSimulation")) { return; }
    var fieldset = document.createElement("fieldset");
    fieldset.id = "localPaymentSimulation";
    fieldset.className = "mb_24";
    var legend = document.createElement("legend");
    legend.textContent = "Local payment simulation";
    fieldset.appendChild(legend);
    var explanation = document.createElement("p");
    explanation.textContent =
      "No real payment will be made and no card or bank information is collected.";
    fieldset.appendChild(explanation);
    [
      ["sandbox-approved", "Simulated approval"],
      ["sandbox-declined", "Simulated decline"],
      ["sandbox-retry", "Simulated retry"]
    ].forEach(function (scenario, index) {
      var row = document.createElement("div");
      var input = document.createElement("input");
      input.type = "radio";
      input.name = "paymentScenario";
      input.value = scenario[0];
      input.id = "paymentScenario-" + scenario[0];
      input.checked = index === 0;
      var label = document.createElement("label");
      label.setAttribute("for", input.id);
      label.textContent = scenario[1];
      row.appendChild(input);
      row.appendChild(label);
      fieldset.appendChild(row);
    });
    var submit = form.querySelector('[type="submit"]');
    if (submit && submit.parentNode) {
      submit.parentNode.insertBefore(fieldset, submit);
    } else {
      form.appendChild(fieldset);
    }
  }

  function buildApplicationWorkflow(form) {
    if (form.querySelector("#applicationWorkflow")) { return; }
    var section = document.createElement("section");
    section.id = "applicationWorkflow";
    section.style.cssText = "border:1px solid #ccc;padding:18px;margin:20px 0;background:#fff";
    section.innerHTML =
      '<h2>Application review</h2>' +
      '<div id="eligibility-summary" role="status">Checking location eligibility…</div>' +
      '<fieldset id="risk-questions"><legend>Pet health / risk questions</legend>' +
      '<p>This offline-modeled step exercises required and conditional application validation.</p>' +
      '<p><strong>Is your pet currently ill? *</strong> ' +
      '<label><input type="radio" name="currentlyIll" value="false"> No</label> ' +
      '<label><input type="radio" name="currentlyIll" value="true"> Yes</label></p>' +
      '<label id="condition-details-wrap" hidden>Condition details *' +
      '<textarea name="conditionDetails" rows="2"></textarea></label>' +
      '<p><strong>Has your pet seen a vet in the last 12 months? *</strong> ' +
      '<label><input type="radio" name="seenVet" value="false"> No</label> ' +
      '<label><input type="radio" name="seenVet" value="true"> Yes</label></p>' +
      '<label id="vet-name-wrap" hidden>Veterinary provider *' +
      '<input name="vetName" type="text"></label></fieldset>' +
      '<fieldset><legend>Consent / E-sign</legend>' +
      '<label><input type="checkbox" name="privacyConsent"> I acknowledge the privacy notice.</label><br>' +
      '<label><input type="checkbox" name="electronicSignature"> I agree to use an electronic signature.</label>' +
      '</fieldset><p id="application-errors" class="formErrors" role="alert"></p>' +
      '<button id="review-application" type="button" class="button button_secondary">Review application</button>' +
      '<div id="application-review-summary" hidden tabindex="-1"><h3>Review your application</h3>' +
      '<pre id="application-review-copy" style="white-space:pre-wrap"></pre>' +
      '<button id="edit-application" type="button" class="button button_secondary">Edit prior details</button>' +
      '<p id="application-saved" role="status"></p></div>';
    var submit = form.querySelector('[type="submit"]');
    if (submit && submit.parentNode) {
      submit.parentNode.insertBefore(section, submit);
    } else { form.appendChild(section); }

    function conditionalState() {
      var ill = radioValue(form, "currentlyIll");
      var seen = radioValue(form, "seenVet");
      document.getElementById("condition-details-wrap").hidden = ill !== "true";
      document.getElementById("vet-name-wrap").hidden = seen !== "true";
    }
    Array.prototype.forEach.call(
      section.querySelectorAll('input[type="radio"]'),
      function (radio) { radio.addEventListener("change", conditionalState); });

    api("GET", "/api/quotes/" + getQuoteId() + "/eligibility")
      .then(function (res) {
        var summary = document.getElementById("eligibility-summary");
        if (res.status === 200) {
          summary.textContent = "Eligible in " + res.data.state + " (ZIP " +
            res.data.zip + "). Enrollment fee: $" + res.data.enrollment_fee +
            " " + res.data.currency + ". Location selection is saved.";
        } else { summary.textContent = "Eligibility could not be loaded."; }
      });

    api("GET", "/api/quotes/" + getQuoteId() + "/application")
      .then(function (res) {
        if (res.status !== 200 || !res.data.review_ready) { return; }
        var contact = res.data.contact || {};
        [
          ["firstName", "first_name"],
          ["lastName", "last_name"],
          ["address1", "address"],
          ["city", "city"],
          ["stateSelect", "state"],
          ["zipcode", "zip"],
          ["phone", "phone"]
        ].forEach(function (mapping) {
          if (form.elements[mapping[0]] && contact[mapping[1]] !== undefined) {
            form.elements[mapping[0]].value = contact[mapping[1]] || "";
          }
        });
        var questions = res.data.questions || {};
        var consent = res.data.consent || {};
        var ill = form.querySelector('input[name="currentlyIll"][value="' +
          String(questions.currently_ill) + '"]');
        var seen = form.querySelector('input[name="seenVet"][value="' +
          String(questions.seen_vet_last_12_months) + '"]');
        if (ill) { ill.checked = true; }
        if (seen) { seen.checked = true; }
        if (form.elements.conditionDetails) {
          form.elements.conditionDetails.value = questions.condition_details || "";
        }
        if (form.elements.vetName) {
          form.elements.vetName.value = questions.vet_name || "";
        }
        form.elements.privacyConsent.checked = consent.privacy === true;
        form.elements.electronicSignature.checked =
          consent.electronic_signature === true;
        conditionalState();
        showApplicationReview(res.data);
      });

    function showApplicationReview(application) {
      var selection = getSelection() || {};
      var copy = [
        "Applicant: " + application.contact.first_name + " " + application.contact.last_name,
        "Address: " + (application.contact.address || "") + ", " +
          (application.contact.city || "") + ", " + (application.contact.state || "") +
          " " + (application.contact.zip || ""),
        "Currently ill: " + (application.questions.currently_ill ? "Yes" : "No"),
        "Vet in last 12 months: " +
          (application.questions.seen_vet_last_12_months ? "Yes" : "No"),
        "Coverage: $" + Number(selection.limit || 0).toLocaleString("en-US") +
          " limit / $" + (selection.deductible || "") + " deductible / " +
          (selection.reimbursement || "") + "% reimbursement",
        "Privacy consent: " + (application.consent.privacy ? "Accepted" : "Not accepted"),
        "Electronic signature: " +
          (application.consent.electronic_signature ? "Accepted" : "Not accepted")
      ];
      document.getElementById("application-review-copy").textContent = copy.join("\n");
      var review = document.getElementById("application-review-summary");
      review.hidden = false;
      document.getElementById("risk-questions").hidden = true;
      document.getElementById("application-saved").textContent =
        "Application review saved. Changes persist after navigation or reload.";
      review.focus();
    }

    document.getElementById("edit-application").addEventListener("click", function () {
      document.getElementById("risk-questions").hidden = false;
      document.getElementById("application-review-summary").hidden = true;
      if (form.elements.city) { form.elements.city.focus(); }
    });

    document.getElementById("review-application").addEventListener("click", function () {
      var errors = [];
      var ill = radioValue(form, "currentlyIll");
      var seen = radioValue(form, "seenVet");
      if (!form.elements.firstName.value.trim()) { errors.push("First name is required."); }
      if (!form.elements.lastName.value.trim()) { errors.push("Last name is required."); }
      if (!ill) { errors.push("Choose whether your pet is currently ill."); }
      if (ill === "true" && !form.elements.conditionDetails.value.trim()) {
        errors.push("Condition details are required when Currently ill is Yes.");
      }
      if (!seen) { errors.push("Choose whether your pet saw a vet in the last 12 months."); }
      if (seen === "true" && !form.elements.vetName.value.trim()) {
        errors.push("Veterinary provider is required when the vet answer is Yes.");
      }
      if (!form.elements.privacyConsent.checked) { errors.push("Privacy consent is required."); }
      if (!form.elements.electronicSignature.checked) {
        errors.push("Electronic signature consent is required.");
      }
      document.getElementById("application-errors").textContent = errors.join(" ");
      if (errors.length) { return; }
      api("PUT", "/api/quotes/" + getQuoteId() + "/application", {
        contact: {
          first_name: form.elements.firstName.value.trim(),
          last_name: form.elements.lastName.value.trim(),
          address: form.elements.address1.value.trim(),
          city: form.elements.city.value.trim(),
          state: form.elements.stateSelect.value,
          zip: form.elements.zipcode.value.trim(),
          phone: form.elements.phone.value.trim()
        },
        questions: {
          currently_ill: ill === "true",
          condition_details: form.elements.conditionDetails.value.trim(),
          seen_vet_last_12_months: seen === "true",
          vet_name: form.elements.vetName.value.trim()
        },
        consent: {
          privacy: form.elements.privacyConsent.checked,
          electronic_signature: form.elements.electronicSignature.checked
        }
      }).then(function (res) {
        if (res.status === 200) { showApplicationReview(res.data); }
        else { document.getElementById("application-errors").textContent =
          (res.data.errors && Object.values(res.data.errors).join(" ")) ||
          "Application review could not be saved."; }
      });
    });
  }

  function submitCheckout(event) {
    event.preventDefault();
    var form = funnelForm();
    clearInsertedErrors(form);
    var invalid = false;
    CHECKOUT_REQUIRED.forEach(function (name) {
      var control = form.elements[name];
      if (!control) { return; }
      var value = control.value.trim();
      var bad = !value;
      var message = null;
      if (name === "email" && (bad || !EMAIL_RE.test(value))) {
        bad = true;
        message = "Enter your email address.";       /* captured copy */
      }
      if (name === "zipcode" && (bad || !ZIP_RE.test(value))) {
        bad = true;
        message = "Enter a valid zip code.";         /* captured copy */
      }
      if (bad) { invalid = true; markInvalid(control, message); }
    });
    var frequency = radioValue(form, "paymentType");
    if (!frequency) {
      invalid = true;
      var freq = form.querySelector('input[name="paymentType"]');
      if (freq) { markInvalid(freq, null); }
    }
    var agree = form.elements.agreeTerms;
    if (!agree || !agree.checked) {
      invalid = true;
      if (agree) { markInvalid(agree, null); }
    }
    var scenario = radioValue(form, "paymentScenario");
    if (!scenario) {
      invalid = true;
      var paymentScenario = form.querySelector('input[name="paymentScenario"]');
      if (paymentScenario) { markInvalid(paymentScenario, null); }
    }
    if (invalid) {
      var banner = buildBanner();
      form.insertBefore(banner, form.firstChild);
      banner.focus();
      return;
    }
    var payload = {
      firstName: form.elements.firstName.value.trim(),
      lastName: form.elements.lastName.value.trim(),
      address1: form.elements.address1.value.trim(),
      address2: form.elements.address2
        ? form.elements.address2.value.trim() : "",
      city: form.elements.city.value.trim(),
      stateSelect: form.elements.stateSelect.value,
      zipcode: form.elements.zipcode.value.trim(),
      phone: form.elements.phone.value.trim(),
      email: form.elements.email.value.trim(),
      marketingCodeSelect: form.elements.marketingCodeSelect
        ? form.elements.marketingCodeSelect.value : "",
      frequency: frequency,
      agree_terms: true,
      paperless: !!(form.elements.paperless && form.elements.paperless.checked),
      scenario_id: scenario
    };
    api("POST", "/api/quotes/" + getQuoteId() + "/enroll", payload)
      .then(function (res) {
        if (res.status === 201 || res.status === 200) {
          /* Truthful local confirmation only — the source flow beyond this
           * point was not captured, so no source-style page is fabricated. */
          form.innerHTML = "";
          var done = document.createElement("p");
          done.className = "ng-binding";
          done.setAttribute("role", "status");
          done.textContent = "Enrollment recorded in the offline clone.";
          form.appendChild(done);
          if (res.data && res.data.policy_number) {
            var policy = document.createElement("p");
            policy.className = "ng-binding";
            policy.textContent = "Policy number: " + res.data.policy_number;
            form.appendChild(policy);
          }
          if (res.data && res.data.summary) {
            var summary = res.data.summary;
            var confirmation = document.createElement("p");
            confirmation.id = "confirmation-summary";
            confirmation.className = "ng-binding";
            confirmation.textContent = "Insured pet: " + summary.pet_name +
              ". Coverage: $" + Number(summary.annual_limit).toLocaleString("en-US") +
              " annual limit, $" + summary.deductible + " deductible, " +
              summary.reimbursement + "% reimbursement. " + summary.frequency +
              " simulated total: $" + summary.amount + " " + summary.currency + ".";
            form.appendChild(confirmation);
          }
          var payment = document.createElement("p");
          payment.className = "ng-binding";
          payment.textContent =
            "Payment: local simulation only (no real charge).";
          form.appendChild(payment);
          var mail = document.createElement("p");
          mail.className = "ng-binding";
          mail.textContent = "Mail: " +
            (res.data && res.data.mail ? res.data.mail.status : "LOCAL_SIMULATION") +
            " (no email sent).";
          form.appendChild(mail);
        } else if (res.status === 402 || res.status === 409) {
          var status = res.data && res.data.payment
            ? res.data.payment.status : "RETRYABLE";
          var paymentSection = form.querySelector("#localPaymentSimulation");
          var message = status === "DECLINED"
            ? "The simulated payment was declined. Choose another sandbox outcome to continue."
            : "The simulated payment can be retried. Choose another sandbox outcome to continue.";
          if (paymentSection) { paymentSection.appendChild(inlineError(message)); }
        } else if (res.status === 422 && res.data && res.data.errors) {
          Object.keys(res.data.errors).forEach(function (field) {
            var control = form.elements[field];
            if (control) { markInvalid(control, res.data.errors[field]); }
          });
          form.insertBefore(buildBanner(), form.firstChild);
        } else {
          apiFailure(new Error("enroll " + res.status));
        }
      }).catch(apiFailure);
  }

  function initCheckout() {
    var form = funnelForm();
    if (form) {
      hydrateCheckout(form);
      buildApplicationWorkflow(form);
      buildLocalPaymentSimulation(form);
      form.addEventListener("submit", submitCheckout);
    }
  }

  /* ------------------------------------------------------------------ */
  /* #/quote-search — captured resume form.                              */

  function submitResume(event) {
    event.preventDefault();
    var form = funnelForm();
    clearInsertedErrors(form);
    var email = form.elements.email.value.trim();
    var zip = form.elements.zipcode.value.trim();
    var invalid = false;
    if (!EMAIL_RE.test(email)) {
      invalid = true;
      markInvalid(form.elements.email, "Enter your email address.");
    }
    if (!ZIP_RE.test(zip)) {
      invalid = true;
      markInvalid(form.elements.zipcode, "Enter a valid zip code.");
    }
    if (invalid) { return; }
    api("GET", "/api/quotes/search?email=" + encodeURIComponent(email) +
        "&zip=" + encodeURIComponent(zip))
      .then(function (res) {
        if (res.status === 200 && res.data && res.data.quote_id) {
          var ready = res.data.rates ? Promise.resolve(res.data)
            : api("GET", "/api/quotes/" + res.data.quote_id)
              .then(function (r) { return r.data; });
          ready.then(function (quote) {
            setQuote(quote);
            sessionStorage.removeItem("aspca.selection");
            window.location.hash = "#/plans";
          });
        } else if (res.status === 404) {
          var note = inlineError("No matching quote found (offline clone).");
          form.insertBefore(note, form.firstChild);
        } else {
          apiFailure(new Error("search " + res.status));
        }
      }).catch(apiFailure);
  }

  function initResume() {
    var form = funnelForm();
    if (form) { form.addEventListener("submit", submitResume); }
  }

  /* ------------------------------------------------------------------ */
  /* #/add-a-pet — captured form; new pet lands on the active quote.     */

  function submitAddPet(event) {
    event.preventDefault();
    var form = funnelForm();
    clearInsertedErrors(form);
    var values = {
      species: radioValue(form, "petSpecies"),
      name: form.elements.petsName.value.trim(),
      age: selectedAgeLabel(form.elements.choAge),
      gender: radioValue(form, "petSex"),
      breed: form.elements.choBreed
        ? form.elements.choBreed.value.trim() : ""
    };
    var invalid = false;
    if (!values.species) { invalid = true; }
    if (!values.name || !PET_NAME_RE.test(values.name)) {
      invalid = true;
      markInvalid(form.elements.petsName, "Enter your pet's name.");
    }
    if (!values.age) {
      invalid = true;
      markInvalid(form.elements.choAge, "Enter your pet's age.");
    }
    if (!values.gender) { invalid = true; }
    if (!values.breed) {
      invalid = true;
      markInvalid(form.elements.choBreed, "Enter your pet's breed.");
    }
    if (invalid) {
      form.insertBefore(buildBanner(), form.firstChild);
      return;
    }
    api("POST", "/api/quotes/" + getQuoteId() + "/pets", values)
      .then(function (res) {
        if (res.status === 201) {
          return api("GET", "/api/quotes/" + getQuoteId())
            .then(function (r) {
              if (r.status === 200) { setQuote(r.data); }
              window.location.hash = "#/plans";
            });
        }
        if (res.status === 422 && res.data && res.data.errors) {
          Object.keys(res.data.errors).forEach(function (field) {
            var control = form.elements[field] ||
              form.elements[field === "name" ? "petsName" : field];
            if (control) { markInvalid(control, res.data.errors[field]); }
          });
          form.insertBefore(buildBanner(), form.firstChild);
          return undefined;
        }
        apiFailure(new Error("pets " + res.status));
        return undefined;
      }).catch(apiFailure);
  }

  function initAddPet() {
    var form = funnelForm();
    if (form) { form.addEventListener("submit", submitAddPet); }
  }

  /* ------------------------------------------------------------------ */
  /* Router.                                                             */

  var INITS = { start: initStart, rates: initPlans, checkout: initCheckout,
    resume: initResume, "add-a-pet": initAddPet };

  function route() {
    var hash = window.location.hash || "#/start";
    hash = hash.split("?")[0];
    var entry = ROUTES[hash];
    if (!entry) { window.location.hash = "#/start"; return; }
    if (entry.guard && !getQuoteId()) {
      window.location.hash = "#/start";
      return;
    }
    document.title = entry.title;
    root.removeAttribute("data-view-ready");
    root.setAttribute("data-view-loading", entry.view);
    render(entry.view, INITS[entry.view]).catch(function (err) {
      if (window.console) { console.error(err); }
    });
  }

  /* Captured decorative anchors use href="#": keep them inert instead of
   * clearing the route. */
  document.addEventListener("click", function (event) {
    var anchor = event.target.closest ? event.target.closest("a") : null;
    if (anchor && anchor.getAttribute("href") === "#") {
      event.preventDefault();
    }
  });

  window.addEventListener("hashchange", route);
  if (!window.location.hash) {
    window.history.replaceState(null, "", "#/start");
  }
  route();
}());
