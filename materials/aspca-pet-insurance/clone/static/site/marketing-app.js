(() => {
  "use strict";

  const COOKIE_DISMISSED_KEY =
    "websitebench.aspca-pet-insurance.cookie-banner-dismissed";

  const select = (selector, root = document) => root.querySelector(selector);
  const selectAll = (selector, root = document) => [
    ...root.querySelectorAll(selector),
  ];

  function setExpanded(button, panel, expanded) {
    button.setAttribute("aria-expanded", String(expanded));
    button.classList.toggle("dropdownBtn--active", expanded);
    panel.classList.toggle("dropdownNav_list--active", expanded);
  }

  function initializeDesktopNavigation() {
    const buttons = selectAll('.dropdownBtn[id^="desktopDropdownBtn-"]');

    const closeAll = (except = null) => {
      buttons.forEach((button) => {
        if (button === except) return;
        const panel = document.getElementById(button.getAttribute("aria-controls"));
        if (panel) setExpanded(button, panel, false);
      });
    };

    buttons.forEach((button) => {
      const panel = document.getElementById(button.getAttribute("aria-controls"));
      if (!panel) return;

      button.addEventListener("click", () => {
        const expanded = button.getAttribute("aria-expanded") === "true";
        closeAll(button);
        setExpanded(button, panel, !expanded);
      });
    });

    document.addEventListener("click", (event) => {
      if (!event.target.closest("#desktopHeaderContainer")) closeAll();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const openButton = buttons.find(
        (button) => button.getAttribute("aria-expanded") === "true",
      );
      closeAll();
      openButton?.focus();
    });
  }

  function initializeMobileNavigation() {
    const menuButton = select("#menuToggle");
    const navigation = select("#mobileNavContainer");
    if (!menuButton || !navigation) return;

    // The captured button pointed at a non-existent #mobileNav node.
    menuButton.setAttribute("aria-controls", navigation.id);

    const setMenuOpen = (open) => {
      menuButton.setAttribute("aria-expanded", String(open));
      navigation.style.display = open ? "flex" : "none";
      select(".hamburger")?.classList.toggle("animate", open);
      select(".header--mobile")?.classList.toggle(
        "mobileHeaderContainer",
        open,
      );
      select("#mobileFreeQuoteBtn")?.classList.toggle("d_block", open);
      document.body.classList.toggle("over", open);
    };

    setMenuOpen(false);
    menuButton.addEventListener("click", () => {
      setMenuOpen(menuButton.getAttribute("aria-expanded") !== "true");
    });

    selectAll('.dropdownBtn[id^="mobileDropdownBtn-"]').forEach((button) => {
      const panel = document.getElementById(button.getAttribute("aria-controls"));
      if (!panel) return;

      const backButton = select(".mobileCategory_backBtn", panel);
      const setSubmenuOpen = (open) => {
        setExpanded(button, panel, open);
        selectAll(".mobileDropdownItem", panel).forEach((item) => {
          item.tabIndex = open ? 0 : -1;
        });
      };

      button.addEventListener("click", () => {
        const open = button.getAttribute("aria-expanded") !== "true";
        setSubmenuOpen(open);
        if (open) backButton?.focus();
      });

      backButton?.addEventListener("click", () => {
        setSubmenuOpen(false);
        button.focus();
      });
    });
  }

  function initializePreferences() {
    const banner = select(".osano-cm-dialog");
    const bannerClose = select(".osano-cm-dialog__close");
    const manage = select(".osano-cm-manage");
    const preferences = select(".osano-cm-info-dialog");
    const preferencesPanel = preferences
      ? select(".osano-cm-info", preferences)
      : null;
    const preferencesClose = select(".osano-cm-info-dialog-header__close");
    const widget = select(".osano-cm-window__widget");
    if (!banner) return;

    const rememberDismissal = () => {
      try {
        localStorage.setItem(COOKIE_DISMISSED_KEY, "true");
      } catch (_error) {
        // Storage may be unavailable in privacy modes; closing still works.
      }
    };

    const wasDismissed = () => {
      try {
        return localStorage.getItem(COOKIE_DISMISSED_KEY) === "true";
      } catch (_error) {
        return false;
      }
    };

    const setWidgetVisible = (visible) => {
      if (!widget) return;
      widget.classList.toggle("osano-cm-widget--hidden", !visible);
      widget.toggleAttribute("hidden", !visible);
    };

    const setBannerOpen = (open) => {
      banner.classList.toggle("osano-cm-dialog--hidden", !open);
      banner.toggleAttribute("inert", !open);
      banner.toggleAttribute("hidden", !open);
      banner.setAttribute("aria-hidden", String(!open));
      if (open) setWidgetVisible(false);
    };

    const setPreferencesOpen = (open) => {
      if (!preferences) return;
      preferences.classList.toggle("osano-cm-info-dialog--hidden", !open);
      preferencesPanel?.classList.toggle("osano-cm-info--open", open);
      preferences.toggleAttribute("inert", !open);
      preferences.toggleAttribute("hidden", !open);
      preferences.setAttribute("aria-hidden", String(!open));
      setWidgetVisible(!open && banner.hasAttribute("hidden"));
      if (open) preferencesClose?.focus();
    };

    const dismiss = () => {
      setBannerOpen(false);
      setPreferencesOpen(false);
      rememberDismissal();
      widget?.focus();
    };

    bannerClose?.addEventListener("click", dismiss);
    preferencesClose?.addEventListener("click", dismiss);
    manage?.addEventListener("click", () => {
      setBannerOpen(false);
      setPreferencesOpen(true);
    });
    widget?.addEventListener("click", () => {
      setBannerOpen(false);
      setPreferencesOpen(true);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && preferences && !preferences.hasAttribute("inert")) {
        dismiss();
      }
    });

    setBannerOpen(!wasDismissed());
    setPreferencesOpen(false);
  }

  function initialize() {
    initializeDesktopNavigation();
    initializeMobileNavigation();
    initializePreferences();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
