/* Member-portal app for the aspca-pet-insurance offline clone.
 *
 * Vanilla JS, no frameworks, no remote loads. Renders captured portal view
 * fragments from /portal/views/<name> and wires the captured forms
 * against /portal/api/* only. The member area is unavailable in this
 * anonymous-only clone: login/forgot/register always surface the server's
 * observed validation outcome — a success state is never fabricated.
 * Credentials are sent in the request body only and are never persisted
 * (no storage, no logging, no restoration into re-rendered fragments).
 */
(function () {
  "use strict";

  /* Captured email ng-pattern (quote-start capture, verbatim). */
  var EMAIL_RE = /[a-z0-9A-Z._%+-]+@[a-z0-9A-Z.-]+\.[a-zA-Z]{2,4}$/;

  var ROUTES = {
    "#/login": { view: "login" },
    "#/forgot-password": { view: "forgot-password" },
    "#/register": { view: "register" }
  };

  var root = document.getElementById("app-root");
  var viewCache = {};
  var lastLoginEmail = "";

  function api(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Accept": "application/json",
        "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; })
        .then(function (data) { return { status: res.status, data: data }; });
    });
  }

  function fetchView(name) {
    if (viewCache[name]) { return Promise.resolve(viewCache[name]); }
    return fetch("/portal/views/" + name).then(function (res) {
      if (!res.ok) { throw new Error("view " + name + ": " + res.status); }
      return res.text();
    }).then(function (text) { viewCache[name] = text; return text; });
  }

  /* The captured portal stylesheet (styles.qe4f056fd46.css) hides the page
   * until the Ionic runtime finishes hydrating:
   *   html:not(.hydrated) body{display:none}
   * On the source site the Stencil loader adds "hydrated" to <html>; the
   * frozen markup keeps the class on the components (e.g. ion-app) but the
   * document element loses it. This clone's runtime mirrors that hydration
   * signal once the first view has rendered. */
  function markHydrated() {
    document.documentElement.classList.add("hydrated");
  }

  /* Layout-critical host styles that the Stencil runtime injects into the
   * Ionic components' shadow roots on the source site. Shadow CSS cannot be
   * frozen with the markup, so without these the split pane stacks as plain
   * blocks (the overlay menu fills the flow and pushes the router outlet to
   * zero height). Restored at boot, mirroring the runtime injection:
   *   - ion-split-pane host: absolute flex row shell
   *   - ion-menu (closed overlay): hidden
   *   - ion-content: the page's flexing scroll region */
  var STRUCTURE_CSS =
    "ion-split-pane{position:absolute;top:0;left:0;right:0;bottom:0;" +
    "display:flex;flex-direction:row;contain:strict}" +
    "ion-menu.menu-type-overlay:not(.show-menu){display:none}" +
    "ion-content{position:relative;display:block;flex:1;width:100%;" +
    "overflow-y:auto}";

  (function injectStructureCss() {
    var style = document.createElement("style");
    style.setAttribute("data-clone-structure", "ionic");
    style.textContent = STRUCTURE_CSS;
    document.head.appendChild(style);
  }());

  /* The frozen views were captured from separate Angular app boots, so each
   * carries its own emulated-encapsulation scope id (login: _ngcontent-lod-*,
   * register: _ngcontent-xvy-*, forgot/validation: _ngcontent-did-*). The
   * component styles frozen into index.html's <head> are all scoped to the
   * login session's id, so views rendered with a different id lose every
   * component rule (the split-pane main pane collapses to zero width and the
   * page paints blank). On the source site Angular stamps one consistent
   * APP_ID across the whole session; this mirrors that by rewriting each
   * view's scope attributes to the id the frozen head styles use. */
  var STYLE_SCOPE = (function detectStyleScope() {
    var styles = document.head.querySelectorAll("style");
    for (var i = 0; i < styles.length; i += 1) {
      var match = /_ngcontent-([a-z0-9]+)-c\d/.exec(styles[i].textContent);
      if (match) { return match[1]; }
    }
    return "lod";
  }());

  function normalizeScope(html) {
    return html.replace(
      /_(ngcontent|nghost)-[a-z0-9]+-c(\d+)/g,
      "_$1-" + STYLE_SCOPE + "-c$2"
    );
  }

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

  function render(name) {
    return fetchView(name).then(function (html) {
      root.removeAttribute("data-view-ready");
      root.innerHTML = normalizeScope(html);
      window.scrollTo(0, 0);
      markHydrated();
      return waitForViewResources();
    });
  }

  function remove(el) {
    if (el && el.parentNode) { el.parentNode.removeChild(el); }
  }

  /* Captured error-span markup (portal-login-validation capture):
   * <span class="input_error"> inside an aria-live container. */
  function errorSpan(text) {
    var span = document.createElement("span");
    span.className = "input_error";
    span.textContent = text;
    return span;
  }

  function markInvalid(control) {
    if (!control) { return; }
    control.classList.add("input_error");
    control.setAttribute("aria-invalid", "true");
  }

  function clearMarks(form) {
    Array.prototype.forEach.call(form.elements, function (el) {
      el.classList.remove("input_error");
      el.removeAttribute("aria-invalid");
    });
    Array.prototype.forEach.call(
      form.querySelectorAll("span.input_error"), remove);
  }

  /* Neutral offline-clone note; never styled as a source success state. */
  function neutralNote(text) {
    var p = document.createElement("p");
    p.className = "input_error";
    p.setAttribute("role", "status");
    p.textContent = text;
    return p;
  }

  /* ---------------------------------------------------------------- */
  /* #/login — captured form; failure states from the captured         */
  /* validation fragment (#invalid_email / #doesNotExist_email).       */

  function showLoginValidation(email, keepId, serverMessage) {
    render("login-validation").then(function () {
      var form = document.getElementById("loginForm");
      if (form && form.elements.emailAddress) {
        form.elements.emailAddress.value = email;
      }
      ["invalid_email", "doesNotExist_email"].forEach(function (id) {
        if (id !== keepId) { remove(document.getElementById(id)); }
      });
      var kept = document.getElementById(keepId);
      if (kept && serverMessage) { kept.textContent = serverMessage; }
      wireLogin();
    });
  }

  function submitLogin(event) {
    event.preventDefault();
    var form = document.getElementById("loginForm");
    clearMarks(form);
    var email = form.elements.emailAddress.value.trim();
    var password = form.elements.password.value;
    lastLoginEmail = email;
    if (!EMAIL_RE.test(email)) {
      showLoginValidation(email, "invalid_email", null);
      return;
    }
    if (!password) {
      markInvalid(form.elements.password);
      return;
    }
    api("/portal/api/login", { email: email, password: password })
      .then(function (res) {
        if (res.status >= 200 && res.status < 300) {
          /* The member area beyond login was never captured; do not fake
           * a logged-in state regardless of what the backend returns. */
          var container = document.getElementById("loginErrors-psw") || form;
          container.appendChild(neutralNote(
            "Member area is not available in this offline clone."));
          return;
        }
        showLoginValidation(email, "doesNotExist_email",
          (res.data && res.data.message) || null);
      }).catch(function () {
        var container = document.getElementById("loginErrors-psw") || form;
        container.appendChild(neutralNote(
          "Request failed (offline clone backend unavailable)."));
      });
  }

  function wireLogin() {
    var form = document.getElementById("loginForm");
    if (form) { form.addEventListener("submit", submitLogin); }
  }

  function initLogin() {
    var form = document.getElementById("loginForm");
    if (form && lastLoginEmail && form.elements.emailAddress) {
      form.elements.emailAddress.value = lastLoginEmail;
    }
    wireLogin();
  }

  /* ---------------------------------------------------------------- */
  /* #/forgot-password — captured step-1 form; server outcome surfaced */
  /* into the captured aria-live container (#errors-step1).            */

  function submitForgot(event) {
    event.preventDefault();
    var form = document.getElementById("forgotPswForm");
    clearMarks(form);
    var control = form.elements.accountEmail;
    var email = control ? control.value.trim() : "";
    var errors = document.getElementById("errors-step1");
    if (errors) {
      errors.innerHTML = "";
      errors.removeAttribute("hidden");
    }
    if (!EMAIL_RE.test(email)) {
      markInvalid(control);
      if (errors) {
        /* Captured copy (portal-login-validation capture). */
        errors.appendChild(errorSpan(
          "Error: The email address you entered is invalid."));
      }
      return;
    }
    api("/portal/api/forgot-password", { email: email })
      .then(function (res) {
        var message = (res.data && res.data.message) ||
          "Error: The email address you entered was not found in our " +
          "records.";                       /* captured copy fallback */
        if (errors) { errors.appendChild(errorSpan(message)); }
      }).catch(function () {
        if (errors) {
          errors.appendChild(neutralNote(
            "Request failed (offline clone backend unavailable)."));
        }
      });
  }

  function initForgot() {
    var form = document.getElementById("forgotPswForm");
    if (form) { form.addEventListener("submit", submitForgot); }
  }

  /* ---------------------------------------------------------------- */
  /* #/register — captured form; client-side checks mark fields and    */
  /* use captured copy where it exists; server outcome surfaced as-is. */

  function submitRegister(event) {
    event.preventDefault();
    var form = document.getElementById("registerForm");
    clearMarks(form);
    var get = function (name) {
      var el = form.elements[name];
      return el ? el.value : "";
    };
    var email = get("email").trim();
    var confirmEmail = get("confirmEmail").trim();
    var password = get("password");
    var confirmPassword = get("confirmPassword");
    var accountNumber = get("accountNumber").trim();
    var zipCode = get("zipCode").trim();
    var emailErrors = document.getElementById("emailAddressErrors");
    var invalid = false;
    if (!EMAIL_RE.test(email)) {
      invalid = true;
      markInvalid(form.elements.email);
      if (emailErrors) {
        emailErrors.removeAttribute("hidden");
        emailErrors.appendChild(errorSpan(
          "Error: The email address you entered is invalid."));
      }
    }
    if (!confirmEmail || confirmEmail !== email) {
      invalid = true;
      markInvalid(form.elements.confirmEmail);
    }
    if (!password) { invalid = true; markInvalid(form.elements.password); }
    if (!confirmPassword || confirmPassword !== password) {
      invalid = true;
      markInvalid(form.elements.confirmPassword);
    }
    if (!accountNumber) {
      invalid = true;
      markInvalid(form.elements.accountNumber);
    }
    if (!zipCode) { invalid = true; markInvalid(form.elements.zipCode); }
    if (invalid) { return; }
    api("/portal/api/register", {
      email: email, accountNumber: accountNumber, zipCode: zipCode
    }).then(function (res) {
      var target = document.getElementById("register-pswErrors") || form;
      target.removeAttribute("hidden");
      if (res.data && res.data.message) {
        target.appendChild(errorSpan(res.data.message));
      } else {
        target.appendChild(neutralNote(
          "Registration is not available in this offline clone."));
      }
    }).catch(function () {
      var target = document.getElementById("register-pswErrors") || form;
      target.removeAttribute("hidden");
      target.appendChild(neutralNote(
        "Request failed (offline clone backend unavailable)."));
    });
  }

  function initRegister() {
    var form = document.getElementById("registerForm");
    if (form) { form.addEventListener("submit", submitRegister); }
  }

  /* ---------------------------------------------------------------- */
  /* Router.                                                           */

  var INITS = { login: initLogin, "forgot-password": initForgot,
    register: initRegister };

  /* Captured navigation controls present in every frozen view: the source
   * page routes them between the login / register / forgot-password states. */
  var NAV_CONTROLS = [
    ["registerBtn", "#/register"],
    ["forgotPswLink", "#/forgot-password"],
    ["backToLoginBtn-step1", "#/login"],
    ["backToLoginBtn-step2", "#/login"],
    ["backToLoginBtn-step3", "#/login"]
  ];

  function wireNav() {
    NAV_CONTROLS.forEach(function (pair) {
      var el = document.getElementById(pair[0]);
      if (el) {
        el.addEventListener("click", function (event) {
          event.preventDefault();
          window.location.hash = pair[1];
        });
      }
    });
  }

  function route() {
    var hash = window.location.hash || "#/login";
    hash = hash.split("?")[0];
    var entry = ROUTES[hash];
    if (!entry) { window.location.hash = "#/login"; return; }
    render(entry.view).then(function () {
      wireNav();
      var init = INITS[entry.view];
      if (init) { init(); }
    }).catch(function (err) {
      if (window.console) { console.error(err); }
    });
  }

  document.addEventListener("click", function (event) {
    var anchor = event.target.closest ? event.target.closest("a") : null;
    if (anchor && anchor.getAttribute("href") === "#") {
      event.preventDefault();
    }
  });

  window.addEventListener("hashchange", route);
  if (!window.location.hash) {
    window.history.replaceState(null, "", "#/login");
  }
  route();
}());
