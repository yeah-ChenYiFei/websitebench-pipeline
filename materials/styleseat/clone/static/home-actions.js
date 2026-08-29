/* Evidence-backed interactions for the captured StyleSeat homepage only. */
(function () {
  "use strict";

  function onHome() {
    return location.pathname.replace(/\/+$/, "") === "/m";
  }

  function navigate(path) {
    location.assign(path);
  }

  function bind(control, handler, label) {
    if (!control || control.dataset.cloneActionBound) return;
    control.dataset.cloneActionBound = "1";
    if (label) control.setAttribute("aria-label", label);
    var nativeControl = /^(BUTTON|A)$/.test(control.tagName);
    if (!nativeControl) {
      control.setAttribute("role", "button");
      if (!control.hasAttribute("tabindex")) control.setAttribute("tabindex", "0");
    }
    control.addEventListener("click", handler, true);
    if (!nativeControl) {
      control.addEventListener("keydown", function (event) {
        if (!event.repeat && (event.key === "Enter" || event.key === " ")) {
          handler(event);
        }
      });
    }
  }

  function bindRoute(control, path, label) {
    bind(control, function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      navigate(path);
    }, label);
  }

  function addStyle() {
    if (document.getElementById("wb-home-only-style")) return;
    var style = document.createElement("style");
    style.id = "wb-home-only-style";
    style.textContent = [
      '.wb-home-drawer-layer[hidden] { display: none !important; }',
      '.wb-home-drawer-layer { background: rgba(0,0,0,.70); inset: 0; position: fixed; z-index: 5000; }',
      '.wb-home-drawer { background: #fff; box-sizing: border-box; height: 100%; overflow: auto; padding: 0 16px 28px; width: 350px; }',
      '.wb-home-drawer-close { background: #fff; border: 0; cursor: pointer; display: block; font-size: 36px; font-weight: 300; height: 44px; margin-left: auto; }',
      '.wb-home-drawer a { align-items: center; border-bottom: 1px solid #e5e5e5; box-sizing: border-box; color: #121111; display: flex; font-size: 15px; min-height: 65px; padding: 12px 4px; text-decoration: none; }',
      '.wb-home-drawer h2 { font-size: 24px; margin: 18px 4px 28px; }',
      '.wb-home-drawer .wb-home-login { background: #121111; border: 0; border-radius: 3px; color: #fff; font-weight: 700; justify-content: center; margin: 20px 0; min-height: 40px; padding: 10px 26px; width: 94px; }',
      '.wb-home-drawer .wb-home-referral { background: #fbfff3; border: 0; font-weight: 700; justify-content: space-between; margin-bottom: 18px; min-height: 52px; padding: 12px; }'
    ].join("\n");
    document.head.appendChild(style);
  }

  function createDrawer(trigger) {
    var layer = document.createElement("div");
    layer.id = "wb-home-drawer-layer";
    layer.className = "wb-home-drawer-layer";
    layer.hidden = true;
    layer.innerHTML = [
      '<aside class="wb-home-drawer" role="dialog" aria-modal="true" aria-label="StyleSeat navigation">',
      '<button class="wb-home-drawer-close" type="button" aria-label="Close menu">×</button>',
      '<a class="wb-home-login" href="/m/login">Log In</a>',
      '<a class="wb-home-referral" href="/m/login">🎁&nbsp;&nbsp; $50 for you, $50 for a friend! <b>›</b></a>',
      '<h2>For Professionals</h2>',
      '<a href="/m/pro-signup">☺&nbsp;&nbsp; Set up my business</a>',
      '<a href="/join/run-your-business">?&nbsp;&nbsp; How to get started</a>',
      '<a href="/join/grow-your-business">▥&nbsp;&nbsp; Grow your business</a>',
      '<a href="/join/manage-your-business">☑&nbsp;&nbsp; Manage your business</a>',
      '<a href="/join/elevate-your-client-experience">✂&nbsp;&nbsp; Elevate your client experience</a>',
      '<h2>For Clients</h2>',
      '<a href="/m/login">☺&nbsp;&nbsp; Sign up to book</a>',
      '<a href="/m/">⌂&nbsp;&nbsp; Home</a>',
      '<a href="/m/search">⌕&nbsp;&nbsp; Search</a>',
      '</aside>'
    ].join("");
    document.body.appendChild(layer);
    var closeButton = layer.querySelector(".wb-home-drawer-close");
    var previousOverflow = "";

    function close() {
      if (layer.hidden) return;
      layer.hidden = true;
      document.body.style.overflow = previousOverflow;
      trigger.setAttribute("aria-expanded", "false");
      trigger.focus();
    }
    closeButton.addEventListener("click", close);
    layer.addEventListener("click", function (event) {
      if (event.target === layer) close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !layer.hidden) {
        event.preventDefault();
        close();
      }
    });
    layer.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") return;
      var focusable = layer.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    return {
      layer: layer,
      open: function () {
        previousOverflow = document.body.style.overflow;
        layer.hidden = false;
        document.body.style.overflow = "hidden";
        trigger.setAttribute("aria-expanded", "true");
        closeButton.focus();
      }
    };
  }

  function bindDrawer() {
    var trigger = document.querySelector('[data-testid="sidebar-toggle"]');
    if (!trigger) return;
    trigger.setAttribute("aria-controls", "wb-home-drawer-layer");
    trigger.setAttribute("aria-expanded", "false");
    var drawer = createDrawer(trigger);
    bind(trigger, function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      drawer.open();
    }, "Open navigation menu");
  }

  function bindSearch() {
    bind(document.querySelector('[data-testid="search"]'), function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var query = document.querySelector('[data-testid="query-input"]');
      var locationInput = document.querySelector('[data-testid="location-input"]');
      var params = new URLSearchParams();
      if (query && query.value.trim()) params.set("q", query.value.trim());
      if (locationInput && locationInput.value.trim()) {
        params.set("location", locationInput.value.trim());
      }
      var suffix = params.toString();
      navigate("/m/search" + (suffix ? "?" + suffix : ""));
    }, "Search beauty professionals");
  }

  function bindServiceTiles() {
    document.querySelectorAll('[data-testid^="search-tile-"]:not([data-testid="search-tile-text"])').forEach(function (tile) {
      var slug = tile.getAttribute("data-testid").replace("search-tile-", "");
      var params = new URLSearchParams();
      params.set("service", slug);
      bindRoute(tile, "/m/search?" + params.toString(), "Find " + slug.replace(/-/g, " ") + " professionals");
    });
  }

  function bindBusinessButtons() {
    bindRoute(
      document.querySelector('[data-testid="header-link-login-button"]'),
      "/m/login",
      "Log in"
    );
    [
      document.querySelector('[data-testid="header-link-setup-my-business"]'),
      document.querySelector('[data-testid="home-hero-set-up-my-business-button"]')
    ].forEach(function (button) {
      bindRoute(button, "/m/pro-signup", "Set up my business");
    });

    document.querySelectorAll("button").forEach(function (button) {
      if (!/^learn more$/i.test((button.textContent || "").trim())) return;
      var card = button.parentElement;
      while (card && card !== document.body) {
        var text = (card.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (text.indexOf("grow your business") >= 0) {
          return bindRoute(button, "/join/grow-your-business", "Learn more about growing your business");
        }
        if (text.indexOf("manage your business") >= 0) {
          return bindRoute(button, "/join/manage-your-business", "Learn more about managing your business");
        }
        if (text.indexOf("elevate your client experience") >= 0) {
          return bindRoute(button, "/join/elevate-your-client-experience", "Learn more about client experience");
        }
        if (text.indexOf("set up your business") >= 0) {
          return bindRoute(button, "/join/run-your-business", "Learn more about setting up your business");
        }
        card = card.parentElement;
      }
    });
  }

  function bindAccordions() {
    document.querySelectorAll('[data-testid="accordion-section"]').forEach(function (section, index) {
      var trigger = section.querySelector('[tabindex="0"]');
      var box = section.querySelector('[data-testid="seo-accordion-box"]');
      if (!trigger || !box) return;
      if (!box.id) box.id = "wb-home-accordion-panel-" + index;
      trigger.setAttribute("aria-controls", box.id);
      trigger.setAttribute("aria-expanded", "false");
      box.setAttribute("aria-hidden", "true");
      box.setAttribute("role", "region");
      box.style.height = "0px";
      box.style.overflow = "hidden";
      bind(trigger, function (event) {
        event.preventDefault();
        var opening = trigger.getAttribute("aria-expanded") !== "true";
        document.querySelectorAll('[data-testid="accordion-section"]').forEach(function (other) {
          var otherTrigger = other.querySelector('[tabindex="0"]');
          var otherBox = other.querySelector('[data-testid="seo-accordion-box"]');
          if (otherTrigger) otherTrigger.setAttribute("aria-expanded", "false");
          if (otherBox) {
            otherBox.setAttribute("aria-hidden", "true");
            otherBox.style.height = "0px";
            otherBox.style.overflow = "hidden";
          }
        });
        trigger.setAttribute("aria-expanded", String(opening));
        box.setAttribute("aria-hidden", String(!opening));
        box.style.height = opening ? "auto" : "0px";
        box.style.overflow = opening ? "visible" : "hidden";
      });
    });
  }

  function boot() {
    if (!onHome()) return;
    addStyle();
    bindDrawer();
    bindSearch();
    bindServiceTiles();
    bindBusinessButtons();
    bindAccordions();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
