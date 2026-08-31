const closeMenus = () => {
  document.querySelectorAll("[data-dropdown].open").forEach((menu) => menu.classList.remove("open"));
  document.querySelectorAll("[data-dropdown-toggle]").forEach((button) => button.setAttribute("aria-expanded", "false"));
};

const closeMobileMenu = () => {
  document.body.classList.remove("menu-open");
  const button = document.querySelector("[data-menu-toggle]");
  if (button) button.setAttribute("aria-expanded", "false");
};

document.addEventListener("click", async (event) => {
  const mobileToggle = event.target.closest("[data-menu-toggle]");
  if (mobileToggle) {
    const open = document.body.classList.toggle("menu-open");
    mobileToggle.setAttribute("aria-expanded", String(open));
    closeMenus();
    return;
  }
  if (event.target.closest("[data-menu-close]")) {
    closeMobileMenu();
    closeMenus();
    return;
  }
  const dropdownToggle = event.target.closest("[data-dropdown-toggle]");
  if (dropdownToggle) {
    const target = document.querySelector(`[data-dropdown="${dropdownToggle.dataset.dropdownToggle}"]`);
    const willOpen = target && !target.classList.contains("open");
    closeMenus();
    if (target && willOpen) {
      target.classList.add("open");
      dropdownToggle.setAttribute("aria-expanded", "true");
    }
    return;
  }
  if (!event.target.closest(".nav-group")) closeMenus();

  const player = event.target.closest("[data-player-action]");
  if (player) {
    const shell = player.closest("[data-player]");
    const action = player.dataset.playerAction;
    if (action === "toggle") {
      const playing = player.dataset.state !== "playing";
      player.dataset.state = playing ? "playing" : "paused";
      player.textContent = playing ? "Pause" : "Play";
      shell.querySelector(".screen").setAttribute("data-state", playing ? "playing" : "paused");
    }
    if (action === "fullscreen") {
      const screen = shell.querySelector(".screen");
      if (document.fullscreenElement) document.exitFullscreen();
      else if (screen.requestFullscreen) screen.requestFullscreen();
    }
  }

  const dialogOpen = event.target.closest("[data-dialog-open]");
  if (dialogOpen) {
    const dialog = document.getElementById(dialogOpen.dataset.dialogOpen);
    if (dialog && dialog.showModal) dialog.showModal();
  }
  const dialogClose = event.target.closest("[data-dialog-close]");
  if (dialogClose) dialogClose.closest("dialog")?.close();

  const cart = event.target.closest("[data-cart-add]");
  if (cart) {
    cart.textContent = "Added ✓";
    cart.disabled = true;
    const status = document.querySelector("[data-cart-status]");
    if (status) status.hidden = false;
  }
  const reader = event.target.closest("[data-reader-next]");
  if (reader) {
    reader.textContent = "End of Preview";
    reader.disabled = true;
    const status = document.querySelector("[data-reader-status]");
    if (status) status.hidden = false;
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeMenus();
    closeMobileMenu();
  }
});

document.addEventListener("change", async (event) => {
  const seek = event.target.closest("[data-progress]");
  if (seek) {
    const output = document.querySelector("[data-progress-output]");
    if (output) output.textContent = Math.floor(Number(seek.value) / 60) + "m";
    await fetch("/api/progress", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({episode_id: seek.dataset.episode, position: Number(seek.value), duration: Number(seek.max)}),
    });
  }
});
