/* Crumbl Cookies offline clone — account page sign-out (external script so
   it satisfies the same-origin CSP). */
(function () {
  "use strict";
  var btn = document.getElementById("account-signout");
  if (!btn) return;
  btn.addEventListener("click", function () {
    fetch("/api/auth/signout", { method: "POST" }).then(function () {
      window.location.href = "/";
    }).catch(function () {
      window.location.href = "/";
    });
  });
})();
