/* Printable itinerary: the page is complete without this, and the control that
   needs scripting only appears once scripting is there to serve it. */
(function () {
  "use strict";

  var trigger = document.querySelector("[data-print-trigger]");
  if (!trigger) return;
  trigger.hidden = false;
  trigger.addEventListener("click", function () {
    window.print();
  });
})();
