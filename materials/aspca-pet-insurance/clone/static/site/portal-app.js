/* Member-portal app for the aspca-pet-insurance offline clone.
 *
 * Vanilla JS, no frameworks, no remote loads. Renders captured portal view
 * fragments from /portal/views/<name> and wires the captured forms
 * against /portal/api/* only. Auth entry screens retain the anonymous source
 * capture; authenticated policy, claim, billing and document states are
 * clearly local, persistent workflows backed by the generated site runtime.
 * Credentials are sent in request bodies only and are never stored by JS.
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

  function request(url, method, body) {
    return fetch(url, {
      method: method || "GET",
      headers: { "Accept": "application/json",
        "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; })
        .then(function (data) { return { status: res.status, data: data }; });
    });
  }

  function api(url, body) { return request(url, "POST", body); }

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
          window.location.hash = "#/home";
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
        if (errors) { errors.appendChild(neutralNote(message)); }
        if (res.status === 202) {
          request("/portal/api/local-inbox/password-reset", "GET")
            .then(function (mail) {
              if (mail.status === 200) { showPasswordReset(mail.data); }
            });
        }
      }).catch(function () {
        if (errors) {
          errors.appendChild(neutralNote(
            "Request failed (offline clone backend unavailable)."));
        }
      });
  }

  function initForgot() {
    var form = document.getElementById("forgotPswForm");
    if (form) {
      var submit = form.querySelector("button[type='submit']");
      if (submit) { submit.disabled = false; }
      form.addEventListener("submit", submitForgot);
    }
  }

  function showPasswordReset(mail) {
    var code = mail.verification_code;
    root.innerHTML = memberShell(
      "Reset password",
      '<p class="local-sim">Local email simulation code: <strong id="local-reset-code">' +
      escapeHtml(code) + '</strong></p>' +
      '<form id="reset-form" class="member-form">' +
      '<label>Verification Code *<input name="code" maxlength="6" required></label>' +
      '<label>New Password *<input name="password" type="password" minlength="8" required></label>' +
      '<button class="button button_primary" type="submit">Set new password</button>' +
      '<p id="reset-status" role="status"></p></form>'
    );
    readyMember();
    document.getElementById("reset-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var form = event.currentTarget;
      api("/portal/api/password-reset/verify", {
        code: form.elements.code.value,
        new_password: form.elements.password.value
      }).then(function (res) {
        var status = document.getElementById("reset-status");
        if (res.status === 200) {
          status.textContent = "Password updated. You are signed in.";
          window.location.hash = "#/home";
        } else {
          status.textContent = firstError(res.data) || "Password reset failed.";
        }
      });
    });
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
      email: email,
      password: password,
      display_name: "Member " + accountNumber,
      accept_terms: true,
      account_number: accountNumber,
      zip: zipCode
    }).then(function (res) {
      var target = document.getElementById("register-pswErrors") || form;
      target.removeAttribute("hidden");
      if (res.status === 202) {
        showRegistrationVerification(email);
      } else if (res.data && res.data.message) {
        target.appendChild(errorSpan(res.data.message));
      } else {
        target.appendChild(errorSpan(firstError(res.data) ||
          "Registration could not be started."));
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
    if (form) {
      var submit = form.querySelector("button[type='submit']");
      if (submit) { submit.disabled = false; }
      form.addEventListener("submit", submitRegister);
    }
  }

  function showRegistrationVerification(email) {
    request("/portal/api/local-inbox/registration", "GET")
      .then(function (mail) {
        if (mail.status !== 200) { throw new Error("local inbox unavailable"); }
        root.innerHTML = memberShell(
          "Verify your account",
          '<p>A verification message for <strong>' + escapeHtml(email) +
          '</strong> is available in the local simulation inbox.</p>' +
          '<p class="local-sim">Local email simulation code: <strong id="local-registration-code">' +
          escapeHtml(mail.data.verification_code) + '</strong></p>' +
          '<form id="verify-registration" class="member-form">' +
          '<label>Verification Code *<input name="code" maxlength="6" required></label>' +
          '<button class="button button_primary" type="submit">Verify and create account</button>' +
          '<p id="verify-status" role="status"></p></form>'
        );
        readyMember();
        document.getElementById("verify-registration")
          .addEventListener("submit", function (event) {
            event.preventDefault();
            api("/portal/api/register/verify", {
              code: event.currentTarget.elements.code.value
            }).then(function (res) {
              if (res.status === 201) {
                window.location.hash = "#/home";
              } else {
                document.getElementById("verify-status").textContent =
                  firstError(res.data) || "Verification failed.";
              }
            });
          });
      }).catch(function () {
        var target = document.getElementById("register-pswErrors") || root;
        target.appendChild(neutralNote("Local verification inbox unavailable."));
      });
  }

  /* ---------------------------------------------------------------- */
  /* Authenticated local member center. The navigation labels are from */
  /* the captured portal shell; state comes only from the local API.   */

  var MEMBER_CSS =
    ".member-app{min-height:100vh;background:#f6f7f8;color:#242424;font-family:Arial,sans-serif}" +
    ".member-header{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;background:#fff;border-bottom:1px solid #ddd}" +
    ".member-header img{width:210px}.member-layout{display:grid;grid-template-columns:230px 1fr;max-width:1200px;margin:auto}" +
    ".member-nav{background:#fff;min-height:calc(100vh - 84px);padding:24px 0;border-right:1px solid #ddd}" +
    ".member-nav a,.member-nav button{display:block;width:100%;box-sizing:border-box;padding:12px 24px;border:0;background:none;color:#124f70;text-align:left;font:inherit;text-decoration:none}" +
    ".member-nav a:hover,.member-nav a:focus,.member-nav button:hover,.member-nav button:focus{background:#e9f7fa;text-decoration:underline}" +
    ".member-main{padding:32px;min-width:0}.member-main h1{color:#153f5f;margin-top:0}.member-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}" +
    ".member-card{background:#fff;border:1px solid #d6d6d6;border-radius:10px;padding:20px;margin-bottom:18px;box-shadow:0 2px 5px #00000012}" +
    ".member-card h2,.member-card h3{color:#153f5f;margin-top:0}.member-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}" +
    ".member-actions a,.member-actions button,.member-form button{display:inline-block;border:2px solid #f26b21;border-radius:4px;padding:10px 16px;background:#f26b21;color:#fff;font-weight:700;text-decoration:none;cursor:pointer}" +
    ".member-actions .secondary{background:#fff;color:#a9470f}.member-form{display:grid;gap:14px;max-width:620px}" +
    ".member-form label{display:grid;gap:5px;font-weight:700}.member-form input,.member-form select,.member-form textarea{font:inherit;border:1px solid #777;border-radius:4px;padding:10px;background:#fff}" +
    ".member-form input[type=checkbox]{width:auto}.member-form .check{display:flex;align-items:center;gap:8px}.local-sim{border-left:5px solid #00a6b2;background:#e9f7fa;padding:14px}" +
    ".status-pill{display:inline-block;border-radius:999px;padding:4px 10px;background:#e9f7fa;font-weight:700;text-transform:capitalize}" +
    ".status-pill.canceled{background:#f5e4e4;color:#831818}.member-dl{display:grid;grid-template-columns:max-content 1fr;gap:7px 14px}.member-dl dt{font-weight:700}" +
    ".upload-progress{height:12px;background:#ddd;border-radius:6px;overflow:hidden}.upload-progress span{display:block;height:100%;background:#00a6b2}" +
    "@media(max-width:760px){.member-layout{display:block}.member-nav{display:flex;overflow-x:auto;min-height:auto;border-right:0;border-bottom:1px solid #ddd;padding:0}.member-nav a,.member-nav button{width:auto;white-space:nowrap;padding:12px}.member-main{padding:20px}.member-header img{width:170px}}";

  (function injectMemberCss() {
    var style = document.createElement("style");
    style.setAttribute("data-clone-member", "true");
    style.textContent = MEMBER_CSS;
    document.head.appendChild(style);
  }());

  function escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function firstError(data) {
    if (!data) { return ""; }
    if (data.message) { return data.message; }
    if (data.error) { return data.error; }
    if (data.errors) {
      var keys = Object.keys(data.errors);
      return keys.length ? data.errors[keys[0]] : "";
    }
    return "";
  }

  function memberShell(title, content) {
    return '<div class="member-app">' +
      '<header class="member-header"><a href="#/home"><img src="/static/assets/2026-08-13.aspca-pet-insurance-r1/d3544la1u8djza.cloudfront.net/APHI/Logos/aphi_logo_orange.svg" alt="ASPCA Pet Health Insurance"></a>' +
      '<a href="/about-us/contact-us/">Help &amp; Contact</a></header>' +
      '<div class="member-layout"><nav class="member-nav" aria-label="Member Center">' +
      '<a href="#/home">Home</a><a href="#/claims/start-claim">Submit a Claim</a>' +
      '<a href="#/claims/track-a-claim">Track a Claim</a><a href="#/billing">Billing</a>' +
      '<a href="#/my-account">My Account</a><a href="#/my-pets">My Pets</a>' +
      '<a href="#/help-center">Help Center</a><button id="member-logout" type="button">Log Out</button>' +
      '</nav><main class="member-main"><h1>' + escapeHtml(title) + '</h1>' +
      content + '</main></div></div>';
  }

  function readyMember() {
    markHydrated();
    root.setAttribute("data-view-ready", "true");
    var logout = document.getElementById("member-logout");
    if (logout) {
      logout.addEventListener("click", function () {
        api("/portal/api/logout", {}).then(function () {
          window.location.hash = "#/login";
        });
      });
    }
  }

  function memberError(res) {
    if (res.status === 401) {
      window.location.hash = "#/login";
      return true;
    }
    root.innerHTML = memberShell("Member Center", '<p role="alert">' +
      escapeHtml(firstError(res.data) || "The requested member state is unavailable.") +
      '</p>');
    readyMember();
    return true;
  }

  function policyCard(policy) {
    return '<article class="member-card"><h2>' + escapeHtml(policy.pet.name) +
      '</h2><p><span class="status-pill ' + escapeHtml(policy.status) + '">' +
      escapeHtml(policy.status) + '</span></p><dl class="member-dl">' +
      '<dt>Policy</dt><dd>' + escapeHtml(policy.policy_number) + '</dd>' +
      '<dt>Pet</dt><dd>' + escapeHtml(policy.pet.breed) + ', ' +
      escapeHtml(policy.pet.age_label) + '</dd><dt>Renewal</dt><dd>' +
      escapeHtml(policy.renewal_date) + '</dd><dt>Monthly premium</dt><dd>$' +
      escapeHtml(policy.coverage.monthly) + '</dd></dl><div class="member-actions">' +
      '<a href="#/policies/' + encodeURIComponent(policy.policy_number) + '">View policy</a>' +
      '<a class="secondary" href="#/policies/' + encodeURIComponent(policy.policy_number) +
      '/documents">Documents</a></div></article>';
  }

  function renderDashboard() {
    request("/portal/api/dashboard", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var policies = res.data.policies || [];
      var content = '<section class="member-grid"><div class="member-card"><h2>Active policies</h2><p>' +
        escapeHtml(res.data.metrics.active_policies) + '</p></div><div class="member-card"><h2>Open claims</h2><p>' +
        escapeHtml(res.data.metrics.open_claims) + '</p></div></section>' +
        (policies.length ? policies.map(policyCard).join("") :
          '<div class="member-card"><h2>No policies yet</h2><p>Enroll a quote using the same account email to see it here.</p><div class="member-actions"><a href="/quote/#/start">Start Quote</a></div></div>');
      root.innerHTML = memberShell("Welcome, " + res.data.account.display_name, content);
      readyMember();
    });
  }

  function renderPolicy(policyNumber) {
    request("/portal/api/policies/" + encodeURIComponent(policyNumber), "GET")
      .then(function (res) {
        if (res.status !== 200) { memberError(res); return; }
        var p = res.data;
        var activeActions = p.status === "active" ?
          '<a href="#/policies/' + encodeURIComponent(policyNumber) + '/coverage">Update coverage</a>' +
          '<a class="secondary" href="#/billing">Billing &amp; Autopay</a>' : '';
        var content = '<section class="member-grid"><article class="member-card"><h2>Insured pet</h2>' +
          '<dl class="member-dl"><dt>Name</dt><dd>' + escapeHtml(p.insured.name) +
          '</dd><dt>Species</dt><dd>' + escapeHtml(p.insured.species) + '</dd><dt>Breed</dt><dd>' +
          escapeHtml(p.insured.breed) + '</dd><dt>Age</dt><dd>' + escapeHtml(p.insured.age_label) +
          '</dd><dt>Gender</dt><dd>' + escapeHtml(p.insured.gender) + '</dd></dl></article>' +
          '<article class="member-card"><h2>Coverage</h2><dl class="member-dl"><dt>Annual limit</dt><dd>$' +
          escapeHtml(p.coverage.annual_limit) + '</dd><dt>Deductible</dt><dd>$' +
          escapeHtml(p.coverage.deductible) + '</dd><dt>Reimbursement</dt><dd>' +
          escapeHtml(p.coverage.reimbursement) + '%</dd><dt>Premium</dt><dd>$' +
          escapeHtml(p.coverage.monthly) + '/month</dd></dl></article></section>' +
          '<article class="member-card"><h2>Policy holder / insured details</h2><pre>' +
          escapeHtml(JSON.stringify(p.holder, null, 2)) + '</pre><p>Status: <span class="status-pill ' +
          escapeHtml(p.status) + '">' + escapeHtml(p.status) + '</span></p><div class="member-actions">' +
          activeActions + '<a class="secondary" href="#/policies/' + encodeURIComponent(policyNumber) +
          '/documents">Policy documents</a></div></article>' +
          (p.status === "active" ? '<section class="member-grid"><form id="renew-form" class="member-card"><h2>Renewal</h2><p>Eligible to renew through ' +
          escapeHtml(p.renewal_date) + '.</p><button class="button button_primary" type="submit">Renew policy</button><p id="renew-status" role="status"></p></form>' +
          '<form id="cancel-form" class="member-card member-form"><h2>Cancel policy</h2><label>Reason *<select name="reason" required><option value="">Choose reason</option><option>No longer needed</option><option>Moved to another provider</option><option>Other</option></select></label><label class="check"><input name="confirm" type="checkbox"> I confirm cancellation</label><button type="submit">Cancel policy</button><p id="cancel-status" role="status"></p></form></section>' :
          '<div class="member-card"><h2>Cancellation confirmed</h2><p>This policy is canceled and is not renewal eligible.</p><p>Reason: ' +
          escapeHtml(p.cancel.reason) + '</p></div>');
        root.innerHTML = memberShell("Policy " + policyNumber, content);
        readyMember();
        var renew = document.getElementById("renew-form");
        if (renew) {
          renew.addEventListener("submit", function (event) {
            event.preventDefault();
            api("/portal/api/policies/" + encodeURIComponent(policyNumber) + "/renew", {})
              .then(function (answer) {
                document.getElementById("renew-status").textContent = answer.status === 200 ?
                  "Renewal saved. Next renewal: " + answer.data.renewal_date : firstError(answer.data);
              });
          });
        }
        var cancel = document.getElementById("cancel-form");
        if (cancel) {
          cancel.addEventListener("submit", function (event) {
            event.preventDefault();
            var form = event.currentTarget;
            api("/portal/api/policies/" + encodeURIComponent(policyNumber) + "/cancel", {
              reason: form.elements.reason.value,
              confirm: form.elements.confirm.checked
            }).then(function (answer) {
              if (answer.status === 200) { renderPolicy(policyNumber); }
              else { document.getElementById("cancel-status").textContent = firstError(answer.data); }
            });
          });
        }
      });
  }

  function renderCoverage(policyNumber) {
    request("/portal/api/policies/" + encodeURIComponent(policyNumber), "GET")
      .then(function (res) {
        if (res.status !== 200) { memberError(res); return; }
        var c = res.data.coverage;
        function options(values, selected) {
          return values.map(function (value) { return '<option value="' + value + '"' +
            (String(value) === String(selected) ? ' selected' : '') + '>' + value + '</option>'; }).join("");
        }
        var content = '<form id="coverage-form" class="member-card member-form"><p>Modify options to preview and persist the recalculated local rate.</p>' +
          '<label>Annual Limit<select name="annual_limit">' + options([2500, 5000, 7000, 10000], c.annual_limit) + '</select></label>' +
          '<label>Annual Deductible<select name="deductible">' + options([100, 250, 500, 750], c.deductible) + '</select></label>' +
          '<label>Reimbursement<select name="reimbursement">' + options([70, 80, 90], c.reimbursement) + '</select></label>' +
          '<label>Preventive Care<select name="preventive"><option value="none">None</option><option value="basic"' + (c.preventive === "basic" ? " selected" : "") + '>Basic +$9.95</option><option value="prime"' + (c.preventive === "prime" ? " selected" : "") + '>Prime +$24.95</option></select></label>' +
          '<p>Current base premium: <strong id="coverage-price">$' + escapeHtml(c.monthly) + '/month</strong></p>' +
          '<button type="submit">Save coverage changes</button><p id="coverage-status" role="status"></p></form>';
        root.innerHTML = memberShell("Update Coverage", content);
        readyMember();
        document.getElementById("coverage-form").addEventListener("submit", function (event) {
          event.preventDefault();
          var form = event.currentTarget;
          request("/portal/api/policies/" + encodeURIComponent(policyNumber) + "/coverage", "PATCH", {
            annual_limit: Number(form.elements.annual_limit.value),
            deductible: Number(form.elements.deductible.value),
            reimbursement: Number(form.elements.reimbursement.value),
            preventive: form.elements.preventive.value
          }).then(function (answer) {
            var status = document.getElementById("coverage-status");
            if (answer.status === 200) {
              document.getElementById("coverage-price").textContent = "$" + answer.data.coverage.monthly + "/month";
              status.textContent = "Coverage and pricing saved.";
            } else { status.textContent = firstError(answer.data); }
          });
        });
      });
  }

  function renderDocuments(policyNumber) {
    request("/portal/api/policies/" + encodeURIComponent(policyNumber) + "/documents", "GET")
      .then(function (res) {
        if (res.status !== 200) { memberError(res); return; }
        var content = res.data.documents.map(function (doc) {
          return '<article class="member-card"><h2>' + escapeHtml(doc.title) + '</h2><p>' +
            escapeHtml(doc.kind) + ' · ' + escapeHtml(doc.created_at.slice(0, 10)) +
            '</p><div class="member-actions"><a href="' + escapeHtml(doc.download_url) + '">Download PDF</a></div></article>';
        }).join("");
        root.innerHTML = memberShell("Policy Documents", content);
        readyMember();
      });
  }

  function renderAccount() {
    request("/portal/api/profile", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var p = res.data;
      root.innerHTML = memberShell("My Account", '<article class="member-card"><h2>Personal / Contact Details</h2><dl class="member-dl"><dt>Name</dt><dd>' +
        escapeHtml(p.display_name) + '</dd><dt>Email</dt><dd>' + escapeHtml(p.email) +
        '</dd><dt>Phone</dt><dd>' + escapeHtml(p.phone || "Not provided") +
        '</dd></dl><div class="member-actions"><a class="secondary" href="/about-us/contact-us/">Contact support</a></div></article>');
      readyMember();
    });
  }

  function renderPets() {
    request("/portal/api/dashboard", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var content = res.data.policies.map(function (p) {
        return '<article class="member-card"><h2>' + escapeHtml(p.pet.name) + '</h2><dl class="member-dl"><dt>Species</dt><dd>' +
          escapeHtml(p.pet.species) + '</dd><dt>Breed</dt><dd>' + escapeHtml(p.pet.breed) +
          '</dd><dt>Age</dt><dd>' + escapeHtml(p.pet.age_label) + '</dd><dt>Gender</dt><dd>' +
          escapeHtml(p.pet.gender) + '</dd></dl><div class="member-actions"><a href="#/policies/' +
          encodeURIComponent(p.policy_number) + '">View coverage</a></div></article>';
      }).join("") || '<p>No insured pets.</p>';
      root.innerHTML = memberShell("My Pets", content); readyMember();
    });
  }

  function renderBilling() {
    request("/portal/api/dashboard", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var content = res.data.policies.map(function (p) {
        if (p.status !== "active") { return policyCard(p); }
        return '<form class="member-card member-form billing-form" data-policy="' + escapeHtml(p.policy_number) + '"><h2>' +
          escapeHtml(p.pet.name) + ' · ' + escapeHtml(p.policy_number) + '</h2><p>Base premium $' +
          escapeHtml(p.coverage.monthly) + '/month; preventive $' + escapeHtml(p.coverage.preventive_monthly) +
          '/month.</p><label>Billing frequency<select name="frequency"><option' +
          (p.frequency === "Monthly" ? " selected" : "") + '>Monthly</option><option' +
          (p.frequency === "Annually" ? " selected" : "") + '>Annually</option></select></label>' +
          '<label class="check"><input name="autopay" type="checkbox"' + (p.autopay ? " checked" : "") +
          '> Enable Autopay (local simulation)</label><button type="submit">Save billing settings</button><p class="billing-status" role="status"></p></form>';
      }).join("") || '<p>No policies available.</p>';
      root.innerHTML = memberShell("Billing / Autopay", content); readyMember();
      Array.prototype.forEach.call(document.querySelectorAll(".billing-form"), function (form) {
        form.addEventListener("submit", function (event) {
          event.preventDefault();
          request("/portal/api/policies/" + encodeURIComponent(form.dataset.policy) + "/billing", "PATCH", {
            frequency: form.elements.frequency.value,
            autopay: form.elements.autopay.checked
          }).then(function (answer) {
            form.querySelector(".billing-status").textContent = answer.status === 200 ?
              "Billing saved: $" + answer.data.total + " " + answer.data.frequency +
              "; payment profile " + answer.data.payment_profile + "." : firstError(answer.data);
          });
        });
      });
    });
  }

  function renderClaimStart() {
    request("/portal/api/dashboard", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var policies = res.data.policies.filter(function (p) { return p.status === "active"; });
      var opts = policies.map(function (p) { return '<option value="' + escapeHtml(p.policy_number) + '">' +
        escapeHtml(p.pet.name) + ' · ' + escapeHtml(p.policy_number) + '</option>'; }).join("");
      var content = '<form id="claim-form" class="member-card member-form"><label>Policy *<select name="policy_number" required><option value="">Choose policy</option>' +
        opts + '</select></label><label>Incident date *<input name="incident_date" type="date" required></label>' +
        '<label>Reason *<select name="reason" required><option value="">Choose reason</option><option>Illness</option><option>Accident</option><option>Preventive care</option></select></label>' +
        '<label>Veterinary provider *<input name="provider" required></label><label>Invoice total *<input name="amount" inputmode="decimal" required></label>' +
        '<label class="check"><input name="has_invoice" type="checkbox"> I have an invoice to upload</label>' +
        '<label>Document (PDF, PNG, or JPEG)<input id="claim-file" name="file" type="file" accept=".pdf,.png,.jpg,.jpeg"></label>' +
        '<div class="upload-progress" aria-label="Upload progress"><span id="upload-progress" style="width:0"></span></div><p id="upload-status" role="status">No document selected.</p>' +
        '<button type="submit">Submit claim</button><p id="claim-status" role="status"></p></form>';
      root.innerHTML = memberShell("Submit a Claim", content); readyMember();
      var uploadId = null;
      document.getElementById("claim-file").addEventListener("change", function (event) {
        var file = event.currentTarget.files[0];
        uploadId = null;
        document.getElementById("upload-progress").style.width = "0";
        if (!file) { document.getElementById("upload-status").textContent = "No document selected."; return; }
        document.getElementById("upload-status").textContent = "Parsing " + file.name + "…";
        document.getElementById("upload-progress").style.width = "45%";
        api("/portal/api/uploads", { filename: file.name, content_type: file.type, size: file.size })
          .then(function (answer) {
            if (answer.status === 201) {
              uploadId = answer.data.upload_id;
              document.getElementById("upload-progress").style.width = "100%";
              document.getElementById("upload-status").textContent = "Parsed successfully: " + file.name;
            } else {
              document.getElementById("upload-progress").style.width = "0";
              document.getElementById("upload-status").textContent = firstError(answer.data);
            }
          });
      });
      document.getElementById("claim-form").addEventListener("submit", function (event) {
        event.preventDefault();
        var form = event.currentTarget;
        api("/portal/api/claims", {
          policy_number: form.elements.policy_number.value,
          incident_date: form.elements.incident_date.value,
          reason: form.elements.reason.value,
          provider: form.elements.provider.value,
          amount: form.elements.amount.value,
          has_invoice: form.elements.has_invoice.checked,
          upload_id: uploadId
        }).then(function (answer) {
          if (answer.status === 201) {
            window.location.hash = "#/claims/" + answer.data.claim_number;
          } else { document.getElementById("claim-status").textContent = firstError(answer.data); }
        });
      });
    });
  }

  function renderClaims() {
    request("/portal/api/claims", "GET").then(function (res) {
      if (res.status !== 200) { memberError(res); return; }
      var content = '<section class="member-grid"><div class="member-card"><h2>Submitted</h2><p>' +
        escapeHtml(res.data.metrics.submitted) + '</p></div><div class="member-card"><h2>In review</h2><p>' +
        escapeHtml(res.data.metrics.in_review) + '</p></div></section>' +
        res.data.claims.map(function (claim) {
          return '<article class="member-card"><h2>' + escapeHtml(claim.claim_number) +
            '</h2><p><span class="status-pill">' + escapeHtml(claim.status) +
            '</span></p><p>' + escapeHtml(claim.reason) + ' · $' + escapeHtml(claim.amount) +
            '</p><div class="member-actions"><a href="#/claims/' + escapeHtml(claim.claim_number) + '">View claim</a></div></article>';
        }).join("");
      root.innerHTML = memberShell("Track a Claim", content); readyMember();
    });
  }

  function renderClaimDetail(claimNumber) {
    request("/portal/api/claims/" + encodeURIComponent(claimNumber), "GET")
      .then(function (res) {
        if (res.status !== 200) { memberError(res); return; }
        var c = res.data;
        var evidence = c.evidence.map(function (file) {
          return '<li>' + escapeHtml(file.filename) + ' · ' + escapeHtml(file.parse_status) + '</li>';
        }).join("") || '<li>No evidence uploaded</li>';
        root.innerHTML = memberShell("Claim " + claimNumber,
          '<article class="member-card"><p><span class="status-pill">' + escapeHtml(c.status) +
          '</span></p><dl class="member-dl"><dt>Policy</dt><dd>' + escapeHtml(c.policy_number) +
          '</dd><dt>Incident</dt><dd>' + escapeHtml(c.incident_date) + '</dd><dt>Provider</dt><dd>' +
          escapeHtml(c.provider) + '</dd><dt>Reason</dt><dd>' + escapeHtml(c.reason) +
          '</dd><dt>Amount</dt><dd>$' + escapeHtml(c.amount) + ' ' + escapeHtml(c.currency) +
          '</dd></dl><h2>Evidence</h2><ul>' + evidence +
          '</ul><div class="member-actions"><a class="secondary" href="#/claims/track-a-claim">Back to claims</a><a href="/about-us/contact-us/">Contact support</a></div></article>');
        readyMember();
      });
  }

  function renderHelp() {
    root.innerHTML = memberShell("Help Center",
      '<section class="member-grid"><article class="member-card"><h2>Policy and billing help</h2><p>Review your policy, documents, and billing settings from Member Center.</p><div class="member-actions"><a href="/about-us/contact-us/">Contact Us</a></div></article>' +
      '<article class="member-card"><h2>Claims help</h2><p>Submit or track a claim and keep supporting evidence with the record.</p><div class="member-actions"><a href="#/claims/start-claim">Submit a Claim</a></div></article></section>');
    readyMember();
  }

  function routeMember(hash) {
    if (hash === "#/home") { renderDashboard(); return true; }
    if (hash === "#/my-account") { renderAccount(); return true; }
    if (hash === "#/my-pets") { renderPets(); return true; }
    if (hash === "#/billing") { renderBilling(); return true; }
    if (hash === "#/claims/start-claim") { renderClaimStart(); return true; }
    if (hash === "#/claims/track-a-claim") { renderClaims(); return true; }
    if (hash === "#/help-center") { renderHelp(); return true; }
    var policy = /^#\/policies\/([^/]+)(?:\/(coverage|documents))?$/.exec(hash);
    if (policy) {
      if (policy[2] === "coverage") { renderCoverage(decodeURIComponent(policy[1])); }
      else if (policy[2] === "documents") { renderDocuments(decodeURIComponent(policy[1])); }
      else { renderPolicy(decodeURIComponent(policy[1])); }
      return true;
    }
    var claim = /^#\/claims\/([^/]+)$/.exec(hash);
    if (claim) { renderClaimDetail(decodeURIComponent(claim[1])); return true; }
    return false;
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
    ["back-step1", "#/login"],
    ["back-step2", "#/login"],
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
    if (routeMember(hash)) { return; }
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
