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
    thumbs.forEach(function (t, ti) {
      t.addEventListener("click", function () { show(ti); });
    });
  }

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
