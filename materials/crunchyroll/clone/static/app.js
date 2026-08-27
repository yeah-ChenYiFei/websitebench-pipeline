
document.addEventListener("click", async (event) => {
  const toggle = event.target.closest("[data-menu-toggle]");
  if (toggle) {
    const nav = document.querySelector(".nav");
    const open = nav.style.display === "flex";
    nav.style.display = open ? "" : "flex";
    nav.style.position = open ? "" : "absolute";
    nav.style.top = open ? "" : "56px";
    nav.style.left = open ? "" : "0";
    nav.style.right = open ? "" : "0";
    nav.style.padding = open ? "" : "18px";
    nav.style.background = open ? "" : "#232329";
    nav.style.flexDirection = open ? "" : "column";
    toggle.setAttribute("aria-expanded", String(!open));
  }
  const player = event.target.closest("[data-player-action]");
  if (player) {
    const shell = player.closest("[data-player]");
    const action = player.dataset.playerAction;
    if (action === "toggle") {
      const paused = player.dataset.state !== "playing";
      player.dataset.state = paused ? "playing" : "paused";
      player.textContent = paused ? "Pause" : "Play";
      shell.querySelector(".screen").setAttribute("data-state", paused ? "playing" : "paused");
    }
    if (action === "fullscreen") {
      const screen = shell.querySelector(".screen");
      if (document.fullscreenElement) document.exitFullscreen();
      else if (screen.requestFullscreen) screen.requestFullscreen();
    }
  }
});
document.addEventListener("change", async (event) => {
  const seek = event.target.closest("[data-progress]");
  if (seek) {
    const output = document.querySelector("[data-progress-output]");
    if (output) output.textContent = Math.floor(Number(seek.value) / 60) + "m";
    await fetch("/api/progress", {method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({episode_id:seek.dataset.episode,position:Number(seek.value),duration:Number(seek.max)})});
  }
});
