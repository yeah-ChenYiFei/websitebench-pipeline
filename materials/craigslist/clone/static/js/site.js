/* Craigslist offline clone — small same-origin interactions. */

document.addEventListener("DOMContentLoaded", function () {
  // listing photo gallery
  var gallery = document.querySelector("[data-gallery]");
  if (gallery) {
    var main = gallery.querySelector("[data-gallery-main]");
    var thumbs = gallery.querySelectorAll("[data-gallery-thumb]");
    var index = 0;
    function show(i) {
      if (!thumbs.length) return;
      index = (i + thumbs.length) % thumbs.length;
      main.src = thumbs[index].getAttribute("data-src");
      thumbs.forEach(function (t, ti) {
        t.classList.toggle("active", ti === index);
      });
      var info = gallery.querySelector("[data-gallery-info]");
      if (info) info.textContent = "image " + (index + 1) + " of " + thumbs.length;
    }
    var prev = gallery.querySelector("[data-gallery-prev]");
    var next = gallery.querySelector("[data-gallery-next]");
    if (prev) prev.addEventListener("click", function () { show(index - 1); });
    if (next) next.addEventListener("click", function () { show(index + 1); });
    [prev, next].forEach(function (control) {
      if (!control) return;
      control.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          control.click();
        }
      });
    });
    thumbs.forEach(function (t, ti) {
      t.addEventListener("click", function () { show(ti); });
    });
  }

  // The source homepage uses expandable link groups in the compressed right
  // column (nearby CL, Canadian cities/provinces, US cities/states, worldwide).
  // The captured markup is server-rendered, so restore the same local toggle
  // behavior instead of leaving those visible buttons inert.
  document.querySelectorAll(".cl-link-expando-group").forEach(function (group) {
    var button = group.querySelector(":scope > button");
    var list = group.querySelector(":scope > .list");
    if (!button || !list) return;
    var expanded = window.getComputedStyle(list).display !== "none";
    button.setAttribute("aria-expanded", expanded ? "true" : "false");
    button.addEventListener("click", function () {
      var isOpen = button.getAttribute("aria-expanded") === "true";
      list.style.display = isOpen ? "none" : "flex";
      button.setAttribute("aria-expanded", isOpen ? "false" : "true");
    });
  });

  // Search-card hide controls are local UI state: they remove the selected
  // result from view without a remote request.
  document.querySelectorAll("[data-hide-result]").forEach(function (button) {
    button.addEventListener("click", function () {
      var result = button.closest(".cl-search-result, .cl-static-search-result");
      if (result) result.hidden = true;
    });
  });

  // wizard photo reorder (up/down) + hidden order field
  var photoList = document.querySelector("[data-photo-list]");
  if (photoList) {
    var items = Array.prototype.slice.call(photoList.querySelectorAll("[data-photo-item]"));
    function move(item, delta) {
      var idx = items.indexOf(item);
      var target = idx + delta;
      if (target < 0 || target >= items.length) return;
      var ref = delta > 0 ? items[target].nextSibling : items[target];
      photoList.insertBefore(item, ref);
      items = Array.prototype.slice.call(photoList.querySelectorAll("[data-photo-item]"));
    }
    items.forEach(function (item) {
      var up = item.querySelector("[data-photo-up]");
      var down = item.querySelector("[data-photo-down]");
      if (up) up.addEventListener("click", function () { move(item, -1); });
      if (down) down.addEventListener("click", function () { move(item, 1); });
    });
    var reorderForm = document.querySelector("[data-reorder-form]");
    if (reorderForm) {
      reorderForm.addEventListener("submit", function () {
        var order = Array.prototype.map.call(
          photoList.querySelectorAll("[data-photo-item]"),
          function (el) { return el.getAttribute("data-filename"); }
        );
        reorderForm.querySelector('input[name="order"]').value = order.join(",");
      });
    }
  }
});
