/* Crumbl Cookies offline clone — local simulated sign-in / registration.
   Two steps:
     1. name + phone -> POST /api/auth/begin -> server creates an anonymous
        session and a local registration flow, returning the 6-digit code
        (surfaced here as the "simulated text message").
     2. code -> POST /api/auth/verify -> server verifies, completes the local
        account, and rotates the session into an authenticated one, setting a
        session cookie. The page then reloads as signed in.
   No real SMS is sent and no credential is stored by the client. */
(function () {
  "use strict";
  var form = document.getElementById("login-form");
  var codeStep = document.getElementById("code-step");
  var codeForm = document.getElementById("code-form");
  if (!form || !codeStep || !codeForm) return;

  var nameInput = document.getElementById("full-name");
  var phoneInput = document.getElementById("phone");
  var nameError = document.getElementById("name-error");
  var phoneError = document.getElementById("phone-error");
  var codeInput = document.getElementById("code-input");
  var codeError = document.getElementById("code-error");
  var simSms = document.getElementById("sim-sms");
  var sendBtn = document.getElementById("send-code-btn");
  var verifyBtn = document.getElementById("verify-btn");
  var note = document.getElementById("signin-note");

  var pendingSession = null;
  var pendingIsExisting = false;
  var pendingExpectedCode = null;
  var pendingEmail = null;

  function post(path, payload) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) {
          var err = new Error(data.error || "request failed");
          err.status = resp.status;
          throw err;
        }
        return data;
      });
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var ok = true;
    if (!(nameInput.value || "").trim()) {
      nameError.textContent = "This field is required";
      nameInput.classList.add("field-error");
      ok = false;
    } else {
      nameError.textContent = "";
      nameInput.classList.remove("field-error");
    }
    var digits = (phoneInput.value || "").replace(/\D/g, "");
    if (digits.length < 10) {
      phoneError.textContent =
        digits.length === 0
          ? "This field is required"
          : "The phone number you provided is invalid. Please try a different number.";
      phoneInput.classList.add("field-error");
      ok = false;
    } else {
      phoneError.textContent = "";
      phoneInput.classList.remove("field-error");
    }
    if (!ok) return;

    sendBtn.disabled = true;
    sendBtn.textContent = "Sending…";
    post("/api/auth/begin", {
      phone: digits,
      display_name: nameInput.value.trim(),
    }).then(function (data) {
      pendingSession = data.session_token;
      pendingIsExisting = !!data.is_existing;
      pendingExpectedCode = data.verification_code;
      pendingEmail = data.email || null;
      // Render the simulated text message with the locally generated code.
      simSms.innerHTML =
        '<span class="sms-from">[Simulated SMS · Crumbl]</span><br>' +
        "Your Crumbl verification code is " +
        '<span class="sms-code">' + data.verification_code + "</span>.<br>" +
        "This code was generated locally; no real text message was sent.";
      form.hidden = true;
      codeStep.hidden = false;
      if (note) note.textContent =
        "Enter the code shown above to finish signing in locally.";
      codeInput.focus();
    }).catch(function (err) {
      sendBtn.disabled = false;
      sendBtn.textContent = "Send Confirmation Code";
      phoneError.textContent = err.message;
      phoneInput.classList.add("field-error");
    });
  });

  codeForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var code = (codeInput.value || "").trim();
    if (!/^\d{6}$/.test(code)) {
      codeError.textContent = "Verification code must contain exactly six digits";
      codeInput.classList.add("field-error");
      return;
    }
    codeError.textContent = "";
    codeInput.classList.remove("field-error");
    verifyBtn.disabled = true;
    verifyBtn.textContent = "Verifying…";
    post("/api/auth/verify", {
      session_token: pendingSession,
      code: code,
      is_existing: pendingIsExisting,
      expected_code: pendingExpectedCode,
      email: pendingEmail,
    }).then(function () {
      window.location.href = "/";
    }).catch(function (err) {
      verifyBtn.disabled = false;
      verifyBtn.textContent = "Verify & Sign In";
      codeError.textContent = err.message;
      codeInput.classList.add("field-error");
    });
  });

  // Already signed in (real session cookie): hide the form, show welcome.
  fetch("/api/auth/me", { credentials: "same-origin" })
    .then(function (resp) { return resp.json(); })
    .then(function (user) {
      if (!user || !user.authenticated) return;
      var card = form.closest(".auth-card");
      var heading = card ? card.querySelector("h1") : null;
      if (heading) heading.textContent = "Welcome back";
      var sub = card ? card.querySelector(".sub") : null;
      if (sub) sub.textContent = "You are signed in as " + (user.display_name || "there") + ".";
      var note = card ? card.querySelector(".auth-note") : null;
      if (note) note.textContent = "You can sign out from any page header.";
      form.hidden = true;
      codeStep.hidden = true;
      form.setAttribute("aria-hidden", "true");
    })
    .catch(function () { /* anonymous */ });
})();
