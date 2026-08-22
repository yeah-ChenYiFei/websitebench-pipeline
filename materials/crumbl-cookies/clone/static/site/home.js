/* Crumbl Cookies offline clone — home page interactions.
   Same-origin only; no remote requests are ever made. */
(function () {
  "use strict";

  /* Mobile drawer */
  var toggle = document.querySelector(".menu-toggle");
  var menu = document.getElementById("mobile-menu");
  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      var open = menu.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* Hero carousel */
  var track = document.getElementById("hero-track");
  if (!track) return;
  var slides = Array.prototype.slice.call(track.children);
  if (slides.length < 2) return;
  var dotsHost = document.getElementById("hero-dots");
  var current = 0;
  var timer = null;
  var INTERVAL = 6000;

  function buildDots() {
    if (!dotsHost) return;
    slides.forEach(function (slide, index) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "hero-dot" + (index === 0 ? " active" : "");
      dot.setAttribute("aria-label", "Show slide " + (index + 1) + " of " + slides.length);
      dot.addEventListener("click", function () {
        goTo(index);
        restart();
      });
      dotsHost.appendChild(dot);
    });
  }

  function goTo(index) {
    current = (index + slides.length) % slides.length;
    track.style.transform = "translateX(-" + current * 100 + "%)";
    if (dotsHost) {
      Array.prototype.forEach.call(dotsHost.children, function (dot, i) {
        dot.classList.toggle("active", i === current);
      });
    }
  }

  function restart() {
    if (timer) window.clearInterval(timer);
    timer = window.setInterval(function () {
      goTo(current + 1);
    }, INTERVAL);
  }

  buildDots();
  restart();
})();

/* Cookie consent banner — display-only for one visit. Nothing is stored,
   no request is made, and closing it keeps no state (the clone has no
   analytics or advertising to consent to). */
(function () {
  "use strict";
  function makeBanner() {
    var banner = document.createElement("div");
    banner.className = "cookie-banner";
    banner.innerHTML =
      '<div class="cookie-banner-inner">' +
      "<p>This site uses cookies to improve your experience. This offline " +
      "clone stores no cookies, runs no analytics, and sends no data — the " +
      "banner reproduces the source site's consent surface without any of " +
      "its effects.</p>" +
      '<div class="cookie-banner-actions">' +
      '<button type="button" class="btn-pill btn-white cookie-accept">Accept All</button>' +
      '<button type="button" class="btn-pill btn-white cookie-reject">Reject Non-Essential Cookies</button>' +
      "</div></div>";
    document.body.appendChild(banner);
    var dismiss = function () {
      banner.hidden = true;
      banner.remove();
    };
    banner.querySelector(".cookie-accept").addEventListener("click", dismiss);
    banner.querySelector(".cookie-reject").addEventListener("click", dismiss);
  }
  /* Show on first pageview only within this session, mirroring the source's
     one-time dialog; no persistence of the choice. */
  var shown = false;
  try { shown = sessionStorage.getItem("crumbl-cookie-banner-shown") === "1"; } catch (e) {}
  if (!shown) {
    makeBanner();
    try { sessionStorage.setItem("crumbl-cookie-banner-shown", "1"); } catch (e) {}
  }
})();

/* Signed-in state from the local session cookie. The server resolves the
   HttpOnly session cookie; when signed in, every page header shows
   "Hi, {name}" + "Sign out" instead of "Sign in". Sign out calls the
   server to revoke the session and clears the cookie. No client-side
   credential is ever stored. */
(function () {
  "use strict";

  function headerActions() {
    var host = document.querySelector(".header-actions");
    if (host) return host;
    return document.querySelector(".header-inner");
  }

  function renderAuth(user) {
    var host = headerActions();
    var menu = document.getElementById("mobile-menu");
    if (!host) return;

    var existing = host.querySelector(".header-auth-state");
    if (existing) existing.remove();

    if (!user || !user.authenticated) return;

    var name = user.display_name || "there";
    var wrap = document.createElement("div");
    wrap.className = "header-auth-state";
    wrap.style.display = "flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "0.6rem";

    var hi = document.createElement("span");
    hi.className = "header-user-name";
    hi.textContent = "Hi, " + name;
    wrap.appendChild(hi);

    var out = document.createElement("button");
    out.type = "button";
    out.className = "btn-pill btn-white";
    out.textContent = "Sign out";
    out.style.padding = "0 1rem";
    out.style.minHeight = "36px";
    out.addEventListener("click", function () {
      fetch("/api/auth/signout", { method: "POST" }).then(function () {
        window.location.reload();
      }).catch(function () {
        window.location.reload();
      });
    });
    wrap.appendChild(out);

    host.appendChild(wrap);

    if (menu) {
      var links = menu.querySelectorAll("a[href='/login']");
      links.forEach(function (link) {
        link.textContent = "Hi, " + name;
        link.href = "/account";
        var outLink = document.createElement("a");
        outLink.href = "#";
        outLink.textContent = "Sign out";
        outLink.addEventListener("click", function (event) {
          event.preventDefault();
          fetch("/api/auth/signout", { method: "POST" }).then(function () {
            window.location.reload();
          }).catch(function () {
            window.location.reload();
          });
        });
        link.parentNode.insertBefore(outLink, link.nextSibling);
      });
    }
  }

  fetch("/api/auth/me", { credentials: "same-origin" })
    .then(function (resp) { return resp.json(); })
    .then(function (user) { renderAuth(user); })
    .catch(function () { /* anonymous */ });
})();
