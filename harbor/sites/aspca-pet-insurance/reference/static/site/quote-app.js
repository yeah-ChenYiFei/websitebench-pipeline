/* Quote-funnel app for the aspca-pet-insurance offline clone.
 *
 * Vanilla JS, no frameworks, no remote loads. Renders captured view
 * fragments served from /quote/views/<name> and re-implements the
 * funnel behavior against the local JSON API only. All markup, classes and
 * validation copy come from the capture (2026-08-13.aspca-pet-insurance-r1);
 * business numbers (prices) always come from the API, never from this file.
 * Nothing entered by the user is persisted beyond sessionStorage quote state;
 * no credentials or payment data exist anywhere in this funnel.
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
    }).then(function (text) { viewCache[name] = text; return text; });
  }

  function render(name) {
    return fetchView(name).then(function (html) {
      root.removeAttribute("data-view-ready");
      root.innerHTML = html;
      window.scrollTo(0, 0);
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
      if (res.status === 422 && res.data && res.data.errors) {
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

  function normalizeRates(rates) {
    var out = {};
    if (!rates) { return out; }
    if (Array.isArray(rates)) {
      rates.forEach(function (r) {
        var key = r.tier || r.id || r.name;
        if (key) { out[String(key).toLowerCase()] = r.monthly; }
      });
      return out;
    }
    Object.keys(rates).forEach(function (key) {
      var v = rates[key];
      out[key.toLowerCase()] = (v && typeof v === "object") ? v.monthly : v;
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
      if (res.status >= 200 && res.status < 300) { done(res.data); }
      else { apiFailure(new Error("rate " + res.status)); }
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

  function wireTiers(rates) {
    var options = root.querySelectorAll('li[data-tier][role="radio"]');
    Array.prototype.forEach.call(options, function (option) {
      option.addEventListener("click", function () {
        Array.prototype.forEach.call(options, function (other) {
          other.setAttribute("aria-checked", "false");
          other.classList.remove("eb-tier-selector__option--selected");
        });
        option.setAttribute("aria-checked", "true");
        option.classList.add("eb-tier-selector__option--selected");
        var tier = option.getAttribute("data-tier");
        var monthly = rates[tier];
        var sel = getSelection() || {};
        setSelection({ type: "tier", tier: tier, monthly: monthly,
          preventive: sel.preventive || null });
        if (monthly !== undefined) { updatePricebar(monthly); }
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

  function initPlans() {
    var quote = getQuote() || {};
    if (quote.pet && quote.pet.name) { swapPetName(quote.pet.name); }
    var rates = normalizeRates(quote.rates);
    setTierPrices(rates);
    var sel = getSelection();
    if (sel && sel.monthly !== undefined) {
      updatePricebar(sel.monthly);
      if (sel.type === "tier" && sel.tier) {
        var options = root.querySelectorAll("li[data-tier]");
        Array.prototype.forEach.call(options, function (option) {
          var mine = option.getAttribute("data-tier") === sel.tier;
          option.setAttribute("aria-checked", mine ? "true" : "false");
          option.classList.toggle(
            "eb-tier-selector__option--selected", mine);
        });
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
          setSelection({ type: "tier", tier: tier, monthly: rates[tier],
            preventive: null });
          updatePricebar(rates[tier]);
        }
      }
    }
    wireTiers(rates);
    wireCollapse();
    wireCustomRadios();
    wirePreventive();
  }

  /* ------------------------------------------------------------------ */
  /* #/checkout — captured enrollment form; zero payment fields.         */

  var CHECKOUT_REQUIRED = ["firstName", "lastName", "address1", "city",
    "stateSelect", "zipcode", "phone", "email"];

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
      paperless: !!(form.elements.paperless && form.elements.paperless.checked)
    };
    api("POST", "/api/quotes/" + getQuoteId() + "/enroll", payload)
      .then(function (res) {
        if (res.status === 201) {
          /* Truthful local confirmation only — the source flow beyond this
           * point was not captured, so no source-style page is fabricated. */
          form.innerHTML = "";
          var done = document.createElement("p");
          done.className = "ng-binding";
          done.setAttribute("role", "status");
          done.textContent = "Enrollment recorded (offline clone).";
          form.appendChild(done);
          if (res.data && res.data.policy_number) {
            var policy = document.createElement("p");
            policy.className = "ng-binding";
            policy.textContent = "Policy number: " + res.data.policy_number;
            form.appendChild(policy);
          }
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
    if (form) { form.addEventListener("submit", submitCheckout); }
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
    render(entry.view).then(function () {
      var init = INITS[entry.view];
      if (init) { init(); }
    }).catch(function (err) {
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
