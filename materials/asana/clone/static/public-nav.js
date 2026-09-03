(() => {
  const layer = document.querySelector(".mnav-layer");
  if (!layer) return;

  const buttons = [...document.querySelectorAll("[data-nav-menu]")];
  const panels = [...document.querySelectorAll(".mnav-panel")];
  const scrim = layer.querySelector(".mnav-scrim");
  const transitionMs = 200;
  let currentKey = "";
  let switchTimer = 0;
  let closeTimer = 0;

  const panelFor = key => document.getElementById(`mnav-panel-${key}`);

  const selectButton = key => {
    buttons.forEach(button => {
      const selected = button.dataset.navMenu === key;
      button.classList.toggle("is-menu-active", selected);
      button.setAttribute("aria-expanded", String(selected));
    });
  };

  const showPanel = key => {
    const panel = panelFor(key);
    if (!panel) return;
    panel.classList.add("is-active", "is-entering");
    panel.setAttribute("aria-hidden", "false");
    void panel.offsetWidth;
    requestAnimationFrame(() => panel.classList.remove("is-entering"));
  };

  const closeMenu = () => {
    window.clearTimeout(switchTimer);
    window.clearTimeout(closeTimer);
    selectButton("");
    const panel = panelFor(currentKey);
    if (panel) panel.classList.add("is-leaving");
    layer.classList.remove("is-open");
    currentKey = "";
    closeTimer = window.setTimeout(() => {
      panels.forEach(item => {
        item.classList.remove("is-active", "is-entering", "is-leaving");
        item.setAttribute("aria-hidden", "true");
      });
      layer.hidden = true;
    }, transitionMs);
  };

  const openMenu = key => {
    if (key === currentKey) {
      closeMenu();
      return;
    }

    window.clearTimeout(switchTimer);
    window.clearTimeout(closeTimer);
    selectButton(key);

    if (layer.hidden) {
      layer.hidden = false;
      void layer.offsetWidth;
      layer.classList.add("is-open");
      currentKey = key;
      showPanel(key);
      return;
    }

    const previous = panelFor(currentKey);
    if (previous) previous.classList.add("is-leaving");
    currentKey = key;
    switchTimer = window.setTimeout(() => {
      panels.forEach(item => {
        item.classList.remove("is-active", "is-entering", "is-leaving");
        item.setAttribute("aria-hidden", "true");
      });
      showPanel(key);
    }, transitionMs);
  };

  buttons.forEach(button => {
    button.addEventListener("click", () => openMenu(button.dataset.navMenu));
  });
  scrim.addEventListener("click", closeMenu);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && currentKey) closeMenu();
  });

  document.querySelectorAll(".official-snapshot .faq [role='button'][aria-controls]").forEach(control => {
    const answer = document.getElementById(control.getAttribute("aria-controls"));
    if (!answer) return;
    const toggle = () => {
      const expanded = control.getAttribute("aria-expanded") === "true";
      control.setAttribute("aria-expanded", String(!expanded));
      answer.setAttribute("aria-hidden", String(expanded));
    };
    control.addEventListener("click", toggle);
    control.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
  });
})();
