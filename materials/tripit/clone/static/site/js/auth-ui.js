/* Sign-up form enhancement.

   The account-create form must submit with scripting turned off, so the markup
   ships the submit button enabled and the server is the authority on the User
   Agreement checkbox. When scripting is available this restores the gated
   appearance the live form has: the button starts disabled and unlocks once
   every required checkbox is ticked. */
(function () {
  "use strict";

  var submit = document.getElementById("signup-submit-btn");
  if (!submit) return;
  var gateId = submit.getAttribute("data-requires-checkbox");
  if (!gateId) return;
  var gate = document.getElementById(gateId);
  if (!gate) return;

  function sync() {
    submit.disabled = !gate.checked;
    if (gate.checked) submit.classList.add("sign-up-enabled");
    else submit.classList.remove("sign-up-enabled");
  }

  gate.addEventListener("change", sync);
  sync();
})();
