/* Crumbl Cookies offline clone — flavor profile interactions.
   "Add To Favorites" toggles local-only state (sessionStorage); no remote
   request is made and nothing is persisted server-side. */
(function () {
  "use strict";
  var btn = document.getElementById("favorite-btn");
  if (!btn) return;
  var slug = btn.getAttribute("data-slug") || "";
  var KEY = "crumbl-favorites";

  function load() {
    try {
      var raw = sessionStorage.getItem(KEY);
      var list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }
  function save(list) {
    try {
      sessionStorage.setItem(KEY, JSON.stringify(list));
    } catch (e) { /* storage unavailable */ }
  }
  function paint() {
    var list = load();
    var active = list.indexOf(slug) !== -1;
    btn.textContent = active ? "Favorited" : "Add To Favorites";
    btn.classList.toggle("btn-dark", active);
    btn.classList.toggle("btn-white", !active);
  }
  btn.addEventListener("click", function () {
    var list = load();
    var idx = list.indexOf(slug);
    if (idx !== -1) list.splice(idx, 1);
    else list.push(slug);
    save(list);
    paint();
  });
  paint();
})();
