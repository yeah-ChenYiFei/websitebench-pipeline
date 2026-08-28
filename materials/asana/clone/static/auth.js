// Auth page behavior: login (two-step continue), signup + verify, forgot + reset.
// All requests stay on the local origin.
(function () {
  "use strict";

  function $(sel) { return document.querySelector(sel); }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      credentials: "same-origin",
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    return { ok: res.ok, status: res.status, data: data };
  }

  function showError(el, message) {
    el.textContent = message;
    el.hidden = !message;
  }

  function returnTarget() {
    const u = new URLSearchParams(location.search).get("u");
    return u && u.startsWith("/app") ? u : "/app/home";
  }

  async function showOutbox(purpose) {
    const box = $("#local-outbox");
    if (!box) return;
    const res = await fetch("/api/auth/mail?purpose=" + purpose, { credentials: "same-origin" });
    if (res.ok) {
      const mail = await res.json();
      box.innerHTML = "<strong>Local outbox</strong><br>Subject: " +
        (purpose === "registration" ? "Verify your Asana account" : "Reset your Asana password") +
        '<br>Your code: <span class="code">' + mail.verification_code + "</span>";
    } else {
      box.textContent = "No local mail yet.";
    }
  }

  document.querySelectorAll(".sso").forEach(function (btn) {
    btn.addEventListener("click", function () {
      alert(btn.dataset.sso + " sign-in is not available in this offline demo. " +
        "Use an email account instead.");
    });
  });

  // ---- login: reveal password on first continue, then submit.
  const loginForm = $("#login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const errEl = $("#login-error");
      showError(errEl, "");
      const email = $("#email").value.trim();
      if (!email || email.indexOf("@") < 1) {
        showError(errEl, "Enter a valid email address."); return;
      }
      const pwField = $("#password-field");
      if (pwField.classList.contains("hidden")) {
        pwField.classList.remove("hidden");
        $("#login-continue").textContent = "Log in";
        $("#password").focus();
        return;
      }
      const password = $("#password").value;
      if (!password) { showError(errEl, "Enter your password."); return; }
      const r = await post("/api/auth/login", { email: email, password: password });
      if (r.ok) { location.assign(returnTarget()); }
      else { showError(errEl, r.data.error ? r.data.error.message : "Log in failed."); }
    });
  }

  // ---- signup
  const signupForm = $("#signup-form");
  if (signupForm) {
    signupForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const errEl = $("#signup-error");
      showError(errEl, "");
      const name = $("#name").value.trim();
      const email = $("#email").value.trim();
      const password = $("#password").value;
      if (!name) { showError(errEl, "Enter your full name."); return; }
      if (!email || email.indexOf("@") < 1) { showError(errEl, "Enter a valid email address."); return; }
      if (password.length < 8) { showError(errEl, "Password must be at least 8 characters."); return; }
      const r = await post("/api/auth/signup", { name: name, email: email, password: password });
      if (!r.ok) { showError(errEl, r.data.error ? r.data.error.message : "Sign up failed."); return; }
      signupForm.classList.add("hidden");
      $("#verify-step").classList.remove("hidden");
      await showOutbox("registration");
      $("#code").focus();
    });
    const verifyForm = $("#verify-form");
    verifyForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const errEl = $("#verify-error");
      showError(errEl, "");
      const r = await post("/api/auth/verify", { code: $("#code").value.trim() });
      if (r.ok) { location.assign("/app/home"); }
      else { showError(errEl, r.data.error ? r.data.error.message : "Verification failed."); }
    });
  }

  // ---- forgot / reset
  const forgotForm = $("#forgot-form");
  if (forgotForm) {
    forgotForm.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const errEl = $("#forgot-error");
      showError(errEl, "");
      const email = $("#email").value.trim();
      if (!email || email.indexOf("@") < 1) { showError(errEl, "Enter a valid email address."); return; }
      const r = await post("/api/auth/forgot", { email: email });
      if (!r.ok) { showError(errEl, r.data.error ? r.data.error.message : "Request failed."); return; }
      forgotForm.classList.add("hidden");
      $("#reset-step").classList.remove("hidden");
      await showOutbox("password-reset");
    });
    $("#reset-form").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const errEl = $("#reset-error");
      showError(errEl, "");
      const password = $("#new-password").value;
      if (password.length < 8) { showError(errEl, "Password must be at least 8 characters."); return; }
      const r = await post("/api/auth/reset", { code: $("#code").value.trim(), password: password });
      if (r.ok) {
        location.assign("/-/login");
      } else { showError(errEl, r.data.error ? r.data.error.message : "Reset failed."); }
    });
  }
})();
