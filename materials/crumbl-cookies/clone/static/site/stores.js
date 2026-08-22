(function () {
  "use strict";
  var list = document.getElementById("store-list");
  var noResults = document.getElementById("no-results");
  var form = document.getElementById("store-search");
  var input = document.getElementById("store-query");
  var cards = Array.prototype.slice.call(list.children);
  var original = list.innerHTML;

  function matches(card, query) {
    var text = (card.textContent || "").toLowerCase();
    return text.indexOf(query) === -1 ? false : true;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = (input.value || "").trim().toLowerCase();
    var visible = 0;
    cards.forEach(function (card) {
      var show = !query || matches(card, query);
      if (show) { card.style.display = ""; visible += 1; }
      else { card.style.display = "none"; }
    });
    noResults.hidden = visible > 0;
  });
})();