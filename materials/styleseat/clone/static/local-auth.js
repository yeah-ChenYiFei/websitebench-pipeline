/* Local SMTP-backed account flow for the frozen StyleSeat pages. */
(function () {
  "use strict";

  var API = "/_local/auth";
  var state = { email: "", password: "", displayName: "", flow: "registration", account: null };
  var root = null;

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  async function api(path, payload) {
    var options = { credentials: "same-origin", headers: { "Accept": "application/json" } };
    if (payload !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    var response = await fetch(API + path, options);
    var data = {};
    try { data = await response.json(); } catch (_error) {}
    if (!response.ok) {
      var error = new Error(data.detail || "Something went wrong. Please try again.");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function close() {
    if (root) root.remove();
    root = null;
  }

  function shell(title, description, content) {
    close();
    root = document.createElement("div");
    root.id = "wb-styleseat-auth";
    root.innerHTML =
      '<style>' +
      '#wb-styleseat-auth{position:fixed;inset:0;z-index:2147483000;font-family:Poppins,system-ui,sans-serif;color:#121111}' +
      '#wb-styleseat-auth .wb-backdrop{position:absolute;inset:0;background:rgba(18,17,17,.52)}' +
      '#wb-styleseat-auth .wb-stage{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:20px}' +
      '#wb-styleseat-auth .wb-card{position:relative;width:min(440px,100%);max-height:calc(100vh - 40px);overflow:auto;background:#fff;border-radius:8px;box-shadow:0 18px 60px rgba(0,0,0,.3);padding:32px;box-sizing:border-box}' +
      '#wb-styleseat-auth .wb-close{position:absolute;right:14px;top:12px;border:0;background:transparent;font-size:28px;line-height:1;cursor:pointer}' +
      '#wb-styleseat-auth h2{font-size:24px;line-height:1.25;margin:4px 28px 8px 0}' +
      '#wb-styleseat-auth .wb-copy{color:#595959;font-size:14px;line-height:1.5;margin:0 0 22px}' +
      '#wb-styleseat-auth label{display:block;font-size:13px;font-weight:600;margin:0 0 7px}' +
      '#wb-styleseat-auth .wb-input{width:100%;box-sizing:border-box;border:1px solid #c2c2c2;border-radius:4px;padding:13px 12px;font:inherit;margin:0 0 16px}' +
      '#wb-styleseat-auth .wb-input:focus{outline:2px solid #3313b3;outline-offset:1px}' +
      '#wb-styleseat-auth .wb-primary{width:100%;border:0;border-radius:4px;padding:14px;background:#3313b3;color:#fff;font:inherit;font-weight:600;cursor:pointer}' +
      '#wb-styleseat-auth .wb-primary:disabled{opacity:.55;cursor:wait}' +
      '#wb-styleseat-auth .wb-link{border:0;background:transparent;color:#3313b3;text-decoration:underline;cursor:pointer;padding:9px 0;font:inherit;font-size:13px}' +
      '#wb-styleseat-auth .wb-actions{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:7px}' +
      '#wb-styleseat-auth .wb-error{color:#a71930;font-size:13px;margin:0 0 12px}' +
      '#wb-styleseat-auth .wb-success{color:#176b3a;font-size:13px;margin:0 0 12px}' +
      '#wb-styleseat-auth .wb-codes{display:flex;gap:7px;margin:0 0 18px}' +
      '#wb-styleseat-auth .wb-code{width:calc((100% - 35px)/6);min-width:0;box-sizing:border-box;border:1px solid #c2c2c2;border-radius:4px;padding:12px 2px;text-align:center;font-size:20px}' +
      '</style>' +
      '<div class="wb-backdrop"></div><div class="wb-stage"><section class="wb-card" role="dialog" aria-modal="true" aria-labelledby="wb-auth-title">' +
      '<button class="wb-close" type="button" aria-label="Close">&times;</button>' +
      '<h2 id="wb-auth-title">' + escapeHtml(title) + '</h2>' +
      '<p class="wb-copy">' + description + '</p>' + content + '</section></div>';
    document.body.appendChild(root);
    root.querySelector(".wb-close").addEventListener("click", close);
    root.querySelector(".wb-backdrop").addEventListener("click", close);
    var first = root.querySelector("input,button.wb-primary");
    if (first) first.focus();
  }

  function status(message, success) {
    var target = root && root.querySelector(".wb-status");
    if (!target) return;
    target.innerHTML = '<p role="alert" class="' + (success ? "wb-success" : "wb-error") + '">' +
      escapeHtml(message) + '</p>';
  }

  function passwordView(message) {
    shell(
      "Welcome to StyleSeat",
      "Sign in or create a client account for <strong>" + escapeHtml(state.email) + "</strong>.",
      '<form id="wb-password-form"><div class="wb-status"></div>' +
      '<label for="auth-display-name-input">Name (for a new account)</label>' +
      '<input class="wb-input" id="auth-display-name-input" autocomplete="name" value="' + escapeHtml(state.displayName) + '">' +
      '<label for="auth-password-input">Password</label>' +
      '<input class="wb-input" id="auth-password-input" type="password" autocomplete="current-password" required>' +
      '<button class="wb-primary" type="submit">Continue</button>' +
      '<div class="wb-actions"><button class="wb-link wb-other" type="button">Use another email</button>' +
      '<button class="wb-link wb-forgot" type="button">Forgot password?</button></div></form>'
    );
    if (message) status(message, true);
    root.querySelector(".wb-other").addEventListener("click", function () {
      close();
      if (location.pathname !== "/m/login" && location.pathname !== "/m/signup") location.assign("/m/login");
      var field = document.querySelector('[data-testid="booking-sign-in-and-up-email-text-field"]');
      if (field) field.focus();
    });
    root.querySelector(".wb-forgot").addEventListener("click", startReset);
    root.querySelector("#wb-password-form").addEventListener("submit", submitPassword);
  }

  async function submitPassword(event) {
    event.preventDefault();
    var button = root.querySelector(".wb-primary");
    var password = root.querySelector("#auth-password-input").value;
    state.displayName = root.querySelector("#auth-display-name-input").value.trim();
    state.password = password;
    button.disabled = true;
    try {
      var signedIn = await api("/signin", { email: state.email, password: password });
      if (signedIn.authenticated) {
        state.account = signedIn;
        location.assign("/m/client-appointments");
        return;
      }
    } catch (signInError) {
      if (signInError.status !== 401) {
        button.disabled = false;
        status(signInError.message, false);
        return;
      }
    }
    try {
      await api("/register/start", {
        email: state.email,
        password: password,
        displayName: state.displayName || state.email.split("@")[0]
      });
      state.flow = "registration";
      codeView();
    } catch (registrationError) {
      button.disabled = false;
      status(registrationError.status === 409
        ? "This account already exists. Check your password or reset it."
        : registrationError.message, false);
    }
  }

  function codeInputs() {
    var fields = "";
    for (var index = 0; index < 6; index += 1) {
      fields += '<input class="wb-code" id="code-input-' + index + '" aria-label="Digit ' +
        (index + 1) + ' of 6" type="text" inputmode="numeric" maxlength="1" ' +
        (index === 0 ? 'autocomplete="one-time-code" ' : '') + '>';
    }
    return fields;
  }

  function codeView() {
    shell(
      state.flow === "registration" ? "Verify your email" : "Reset your password",
      "Enter the 6-digit code sent to <strong>" + escapeHtml(state.email) +
        "</strong>. The code expires in 10 minutes.",
      '<form id="wb-code-form"><div class="wb-status"></div><div class="wb-codes">' + codeInputs() + '</div>' +
      '<button class="wb-primary" type="submit">Verify code</button>' +
      '<div class="wb-actions"><button class="wb-link wb-back" type="button">Back</button>' +
      '<span class="wb-copy" style="margin:0">Local SMTP: check Mailpit</span></div></form>'
    );
    var inputs = Array.prototype.slice.call(root.querySelectorAll(".wb-code"));
    inputs.forEach(function (input, index) {
      input.addEventListener("input", function () {
        input.value = input.value.replace(/\D/g, "").slice(-1);
        if (input.value && inputs[index + 1]) inputs[index + 1].focus();
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Backspace" && !input.value && inputs[index - 1]) inputs[index - 1].focus();
      });
    });
    root.querySelector(".wb-back").addEventListener("click", function () {
      if (state.flow === "registration") passwordView(); else passwordView();
    });
    root.querySelector("#wb-code-form").addEventListener("submit", submitCode);
    revealLocalCode();
  }

  async function revealLocalCode() {
    try {
      var purpose = state.flow === "registration" ? "registration" : "password-reset";
      var box = await api("/outbox?purpose=" + encodeURIComponent(purpose));
      if (box.mail && box.mail.verification_code && root) {
        status("Local mailbox code: " + box.mail.verification_code, true);
      }
    } catch (_error) {}
  }

  async function submitCode(event) {
    event.preventDefault();
    var code = Array.prototype.map.call(root.querySelectorAll(".wb-code"), function (input) {
      return input.value;
    }).join("");
    if (code.length !== 6) return status("Enter all 6 digits.", false);
    try {
      if (state.flow === "registration") {
        await api("/register/verify", { code: code });
        state.account = await api("/register/complete", {});
        location.assign("/m/client-appointments");
      } else {
        await api("/reset/verify", { code: code });
        newPasswordView();
      }
    } catch (error) {
      status(error.message, false);
    }
  }

  async function startReset() {
    try {
      await api("/reset/start", { email: state.email });
      state.flow = "password-reset";
      codeView();
    } catch (error) {
      status(error.message, false);
    }
  }

  function newPasswordView() {
    shell(
      "Choose a new password",
      "Use at least 8 characters.",
      '<form id="wb-new-password-form"><div class="wb-status"></div>' +
      '<label for="auth-new-password-input">New password</label>' +
      '<input class="wb-input" id="auth-new-password-input" type="password" autocomplete="new-password" required>' +
      '<button class="wb-primary" type="submit">Set new password</button></form>'
    );
    root.querySelector("#wb-new-password-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        await api("/reset/complete", { password: root.querySelector("#auth-new-password-input").value });
        state.password = "";
        state.flow = "registration";
        passwordView("Password changed. Sign in with your new password.");
      } catch (error) {
        status(error.message, false);
      }
    });
  }

  function accountView() {
    shell(
      "Your StyleSeat account",
      "Signed in as <strong>" + escapeHtml(state.account && (state.account.displayName || state.account.email)) +
        "</strong><br>" + escapeHtml(state.account && state.account.email),
      '<button class="wb-primary wb-signout" type="button">Log out</button>'
    );
    root.querySelector(".wb-signout").addEventListener("click", async function () {
      try { await api("/signout", {}); } catch (_error) {}
      state.account = null;
      location.assign("/m/");
    });
  }

  function bindCapturedLogin() {
    var email = document.querySelector('[data-testid="booking-sign-in-and-up-email-text-field"]');
    var button = document.querySelector('[data-testid="sign-in-and-up-continue-button"]');
    if (!email || !button) return;
    function enable() { button.disabled = !email.value.trim(); }
    email.addEventListener("input", enable);
    email.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && email.value.trim()) {
        event.preventDefault();
        state.email = email.value.trim();
        passwordView();
      }
    });
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      state.email = email.value.trim();
      if (state.email) passwordView();
    }, true);
    enable();
  }

  function bind() {
    bindCapturedLogin();
    document.addEventListener("click", function (event) {
      var login = event.target.closest('[data-testid="header-link-login-button"]');
      var account = event.target.closest('[data-testid="client-my-settings-menu"]');
      if (login) {
        event.preventDefault();
        event.stopImmediatePropagation();
        location.assign("/m/login");
      } else if (account && state.account && (!root || !root.contains(account))) {
        event.preventDefault();
        event.stopImmediatePropagation();
        accountView();
      }
    }, true);
    api("/session").then(function (session) {
      state.account = session.authenticated ? session : null;
    }).catch(function () {});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();
