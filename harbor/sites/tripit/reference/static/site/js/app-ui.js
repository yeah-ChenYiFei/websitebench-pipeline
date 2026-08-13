/* Logged-in shell interactions.

   The live app ships a client framework that hydrates these controls; this
   build reproduces the same behaviours with a small, dependency-free handler:
   Bootstrap-style dropdown menus (nav + trip cards + plan actions), the
   server-rendered trips tab bar, the cookie-preferences dialog, and the
   confirmation step in front of a destructive submit.

   Every control here is an enhancement over markup that already works without
   it: each menu item is a real <a href> or a real <form method="post">, and the
   dialog trigger is a link to the page that renders the same form. */
(function () {
  "use strict";

  var FOCUSABLE =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]),' +
    ' textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function modifierClick(event) {
    // cmd/ctrl/shift/middle-click keeps the browser's own navigation, so a link
    // that also drives an overlay can still be opened in a new tab.
    return event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0;
  }

  // -- dropdown menus -------------------------------------------------------

  function menuFor(el) {
    var group = el.closest(".dropdown");
    return group ? group.querySelector(".dropdown-menu") : null;
  }

  function setOpen(menu, open) {
    if (!menu) return;
    menu.style.display = open ? "block" : "none";
    var group = menu.closest(".dropdown");
    var toggle = group ? group.querySelector(".dropdown-toggle") : null;
    if (toggle) toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function closeAllMenus(except) {
    var menus = document.querySelectorAll(".dropdown-menu");
    for (var i = 0; i < menus.length; i++) {
      if (menus[i] !== except) setOpen(menus[i], false);
    }
  }

  // -- dialog (open / ESC / focus trap / focus restore) ----------------------

  var openDialog = null;
  var dialogOpener = null;

  function focusable(dialog) {
    return Array.prototype.filter.call(
      dialog.querySelectorAll(FOCUSABLE),
      function (el) {
        return el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement;
      }
    );
  }

  function showDialog(dialog, opener) {
    if (openDialog) hideDialog();
    openDialog = dialog;
    dialogOpener = opener || null;
    dialog.hidden = false;
    dialog.setAttribute("aria-hidden", "false");
    if (dialogOpener) dialogOpener.setAttribute("aria-expanded", "true");
    var targets = focusable(dialog);
    if (targets.length) targets[0].focus();
  }

  function hideDialog() {
    if (!openDialog) return;
    openDialog.hidden = true;
    openDialog.setAttribute("aria-hidden", "true");
    if (dialogOpener) {
      dialogOpener.setAttribute("aria-expanded", "false");
      dialogOpener.focus();
    }
    openDialog = null;
    dialogOpener = null;
  }

  function trapTab(event) {
    if (!openDialog || event.key !== "Tab") return;
    var targets = focusable(openDialog);
    if (!targets.length) {
      event.preventDefault();
      return;
    }
    var first = targets[0];
    var last = targets[targets.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!openDialog.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    }
  }

  // -- wiring ---------------------------------------------------------------

  document.addEventListener("click", function (event) {
    // Tab bar: each tab is a real URL so state survives reload and deep links.
    var tab = event.target.closest('button[id^="trips-list-tab-"]');
    if (tab) {
      event.preventDefault();
      var slug = tab.id.slice("trips-list-tab-".length);
      window.location.assign("/app/trips?tab=" + encodeURIComponent(slug));
      return;
    }

    var closer = event.target.closest("[data-dialog-close]");
    if (closer && openDialog) {
      event.preventDefault();
      hideDialog();
      return;
    }

    var opener = event.target.closest("[data-dialog-open]");
    if (opener) {
      if (modifierClick(event)) return;
      var dialog = document.getElementById(opener.getAttribute("data-dialog-open"));
      if (dialog) {
        event.preventDefault();
        closeAllMenus(null);
        showDialog(dialog, opener);
        return;
      }
    }

    if (openDialog && !event.target.closest("._dialogPanel")) {
      // A click on the backdrop dismisses, the same as ESC.
      if (event.target.closest("#" + openDialog.id)) {
        hideDialog();
        return;
      }
    }

    var toggle = event.target.closest(".dropdown-toggle");
    if (toggle) {
      event.preventDefault();
      var menu = menuFor(toggle);
      var willOpen = !!menu && menu.style.display !== "block";
      closeAllMenus(menu);
      setOpen(menu, willOpen);
      return;
    }

    // A click outside any open menu dismisses them all.
    if (!event.target.closest(".dropdown-menu")) closeAllMenus(null);
  });

  // Destructive submits confirm first. Without scripting the form still posts,
  // and the server is the authority either way.
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (!form) return;
    if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" || event.key === "Esc") {
      if (openDialog) {
        hideDialog();
        return;
      }
      closeAllMenus(null);
      return;
    }
    trapTab(event);
  });
})();
