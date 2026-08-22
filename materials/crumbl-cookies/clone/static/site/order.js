/* Crumbl Cookies offline clone — order flow.
   Pure local behavior: state lives in the browser, totals are computed
   locally, checkout posts to the same-origin backend which uses the
   websitebench local-sandbox payment adapter. No remote requests. */
(function () {
  "use strict";

  var app = document.getElementById("order-app");
  if (!app) return;
  var MODE = app.getAttribute("data-mode") || "pickup";

  var FLAVORS = window.__CRUMBL_FLAVORS__ || [];
  var BOXES = window.__CRUMBL_BOXES__ || [
    { id: "4-pack", name: "4-Pack", size: 4, price: 1599 },
    { id: "6-pack", name: "6-Pack", size: 6, price: 2079 },
    { id: "12-pack", name: "12-Pack", size: 12, price: 3899 },
  ];

  var state = {
    store: null,
    boxes: [],           // { box, flavors: [slug,...] }
    cart: [],
    step: "store",
  };

  function loadState() {
    try {
      var raw = sessionStorage.getItem("crumbl-order-" + MODE);
      if (raw) state = JSON.parse(raw);
    } catch (e) { /* fresh session */ }
  }
  function saveState() {
    try {
      sessionStorage.setItem("crumbl-order-" + MODE, JSON.stringify(state));
    } catch (e) { /* storage unavailable */ }
  }

  function cents(n) { return "$" + (n / 100).toFixed(2); }

  function render() {
    var body = document.querySelector(".order-app > .order-body");
    if (!body) return;
    if (state.step === "store") renderStore(body);
    else if (state.step === "build") renderBuild(body);
    else if (state.step === "cart") renderCart(body);
    else if (state.step === "checkout") renderCheckout(body);
    else if (state.step === "review") renderReview(body);
    else if (state.step === "payment") renderPayment(body);
    else if (state.step === "confirm") renderConfirm(body);
    window.scrollTo(0, 0);
  }

  function el(tag, cls, html) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html != null) node.innerHTML = html;
    return node;
  }

  /* ---------------- store select ---------------- */

  function renderStore(body) {
    var head = el("div", "order-step-head",
      "<h1>Select a Store</h1><p>Choose your " + MODE + " store.</p>");
    var grid = el("div", "store-grid");
    grid.setAttribute("data-testid", "store-grid");
    (window.__CRUMBL_STORES__ || []).forEach(function (store) {
      var btn = el("button", "store-option", "");
      btn.type = "button";
      btn.setAttribute("data-testid", "store-select");
      btn.setAttribute("data-slug", store.slug);
      btn.innerHTML = "<h2>" + store.name + "</h2>" +
        "<p>" + store.street + ", " + store.city + ", " + store.stateInitials + " " + store.zip + "</p>" +
        "<p>" + (store.storeHours && store.storeHours.description || "") + "</p>";
      btn.addEventListener("click", function () {
        state.store = store;
        state.step = "build";
        saveState(); render();
      });
      grid.appendChild(btn);
    });
    body.innerHTML = "";
    body.appendChild(head);
    body.appendChild(grid);
  }

  /* ---------------- box build ---------------- */

  function currentBox() {
    return state.boxes[state.boxes.length - 1] || null;
  }

  function renderBuild(body) {
    var box = currentBox();
    var head = el("div", "order-step-head",
      "<h1>Build Your Box</h1><p>" + (state.store ? state.store.name : "") + " · " + (box ? box.box.name : "Choose a box") + "</p>");
    body.innerHTML = "";
    body.appendChild(head);

    if (!box) {
      var grid = el("div", "box-grid");
      grid.setAttribute("data-testid", "box-grid");
      BOXES.forEach(function (b) {
        var btn = el("button", "box-option", "");
        btn.type = "button";
        btn.setAttribute("data-testid", "add-" + b.id);
        btn.innerHTML = "<h2>" + b.name + "</h2><p>" + b.size + " cookies · " + cents(b.price) + "</p>";
        btn.addEventListener("click", function () {
          state.boxes.push({ box: b, flavors: [] });
          saveState(); render();
        });
        grid.appendChild(btn);
      });
      body.appendChild(grid);
      return;
    }

    var remaining = box.box.size - box.flavors.length;
    var label = el("p", "", "Pick " + remaining + " more flavor" + (remaining === 1 ? "" : "s"));
    body.appendChild(label);

    var grid = el("div", "flavor-grid");
    grid.setAttribute("data-testid", "menu-grid");
    FLAVORS.forEach(function (flavor) {
      var count = box.flavors.filter(function (s) { return s === flavor.slug; }).length;
      var selected = count > 0;
      var btn = el("button", "flavor-option" + (selected ? " selected" : ""), "");
      btn.type = "button";
      btn.setAttribute("data-slug", flavor.slug);
      btn.innerHTML = "<h3>" + flavor.name + (count > 1 ? " ×" + count : "") + "</h3>";
      btn.addEventListener("click", function () {
        var idx = box.flavors.indexOf(flavor.slug);
        if (idx !== -1) box.flavors.splice(idx, 1);
        else if (box.flavors.length < box.box.size) box.flavors.push(flavor.slug);
        saveState(); render();
      });
      grid.appendChild(btn);
    });
    body.appendChild(grid);

    var nav = el("div", "step-nav", "");
    if (box.flavors.length === box.box.size) {
      var addMore = el("button", "btn-pill btn-white", "Add Another Box");
      addMore.type = "button";
      addMore.setAttribute("data-testid", "add-another-box");
      addMore.addEventListener("click", function () {
        state.boxes.push({ box: BOXES[1], flavors: [] });
        saveState(); render();
      });
      nav.appendChild(addMore);

      var done = el("button", "btn-pill btn-dark", "Add to Cart");
      done.type = "button";
      done.setAttribute("data-testid", "add-to-cart");
      done.addEventListener("click", function () {
        state.cart = state.cart.concat(state.boxes);
        state.boxes = [];
        state.step = "cart";
        saveState(); render();
      });
      nav.appendChild(done);
    }
    var cancel = el("button", "btn-pill btn-white", "Cancel Box");
    cancel.type = "button";
    cancel.addEventListener("click", function () {
      state.boxes.pop();
      saveState(); render();
    });
    nav.appendChild(cancel);
    body.appendChild(nav);
  }

  /* ---------------- cart ---------------- */

  function cartTotals() {
    var subtotal = state.cart.reduce(function (sum, item) {
      return sum + item.box.price;
    }, 0);
    var discount = state.voucher ? state.voucher.amount_minor : 0;
    var afterDiscount = Math.max(0, subtotal - discount);
    var tax = Math.round(afterDiscount * 0.0825);
    var tip = state.tip ? state.tip : 0;
    return {
      subtotal: subtotal,
      discount: discount,
      tax: tax,
      tip: tip,
      total: afterDiscount + tax + tip,
    };
  }

  function renderCart(body) {
    var t = cartTotals();
    var head = el("div", "order-step-head", "<h1>Your Cart</h1><p>" + (state.store ? state.store.name : "") + "</p>");
    var summary = el("div", "cart-summary", "");
    summary.setAttribute("data-testid", "cart-summary");
    summary.appendChild(el("h2", "", "Items"));
    state.cart.forEach(function (item, i) {
      summary.appendChild(el("div", "cart-item",
        "<span>" + item.box.name + " — " + item.flavors.map(function (slug) {
          var f = FLAVORS.filter(function (x) { return x.slug === slug; })[0];
          return f ? f.name : slug;
        }).join(", ") + "</span><span>" + cents(item.box.price) + "</span>"));
    });
    summary.appendChild(el("div", "cart-total",
      "<span>Subtotal</span><span>" + cents(t.subtotal) + "</span>"));
    summary.appendChild(el("div", "cart-total",
      "<span>Estimated Tax</span><span>" + cents(t.tax) + "</span>"));
    summary.appendChild(el("div", "cart-total",
      "<span>Total</span><span>" + cents(t.total) + "</span>"));

    var nav = el("div", "step-nav", "");
    var back = el("button", "btn-pill btn-white", "Add More");
    back.type = "button";
    back.addEventListener("click", function () {
      state.boxes.push({ box: BOXES[1], flavors: [] });
      state.step = "build"; saveState(); render();
    });
    nav.appendChild(back);
    var checkout = el("button", "btn-pill btn-dark", "Checkout");
    checkout.type = "button";
    checkout.setAttribute("data-testid", "checkout");
    checkout.addEventListener("click", function () {
      state.step = "checkout"; saveState(); render();
    });
    nav.appendChild(checkout);

    body.innerHTML = "";
    body.appendChild(head);
    body.appendChild(summary);
    body.appendChild(nav);
  }

  /* ---------------- checkout (contact / address) ---------------- */

  function renderCheckout(body) {
    var head = el("div", "order-step-head",
      "<h1>" + (MODE === "delivery" ? "Delivery Details" : "Pickup Details") + "</h1><p>Tell us where to bring your cookies.</p>");
    var form = el("form", "form-grid", "");
    form.setAttribute("data-testid", "checkout-review");
    form.setAttribute("novalidate", "novalidate");

    form.appendChild(el("div", "form-field",
      "<label for='contact-name'>Name</label>" +
      "<input id='contact-name' data-testid='pickup-name' name='name' autocomplete='name' placeholder='Full name'>"));

    if (MODE === "delivery") {
      form.appendChild(el("div", "form-field",
        "<label for='delivery-address'>Street Address</label>" +
        "<textarea id='delivery-address' data-testid='delivery-address' name='address' autocomplete='street-address' placeholder='Street address'></textarea>"));
      form.appendChild(el("div", "form-field",
        "<label for='delivery-city'>City, State, ZIP</label>" +
        "<input id='delivery-city' name='citystate' autocomplete='address-level2' placeholder='City, State, ZIP'>"));
    } else {
      form.appendChild(el("div", "form-field",
        "<label for='pickup-time'>Pickup Time</label>" +
        "<select id='pickup-time' name='time'><option>ASAP</option><option>In 30 minutes</option><option>In 1 hour</option></select>"));
    }

    form.appendChild(el("div", "form-field",
      "<label for='order-note'>Add a note</label>" +
      "<textarea id='order-note' name='note' placeholder='Note (optional)'></textarea>"));

    var voucherRow = el("div", "form-field", "");
    voucherRow.innerHTML =
      "<label for='voucher-code'>Voucher / Promo Code</label>" +
      "<div style='display:flex;gap:0.5rem'>" +
      "<input id='voucher-code' name='voucher' placeholder='Voucher / Promo Code' style='flex:1'>" +
      "<button type='button' class='btn-pill btn-white' id='apply-voucher'>Apply</button>" +
      "</div>" +
      "<span class='error' id='voucher-msg'></span>";
    form.appendChild(voucherRow);
    var voucherMsg = form.querySelector("#voucher-msg");

    function clearVoucherMsg() {
      if (voucherMsg) { voucherMsg.textContent = ""; }
    }

    function applyVoucher() {
      var voucherInput = form.querySelector("#voucher-code");
      clearVoucherMsg();
      if (!voucherInput || !voucherInput.value.trim()) {
        state.voucher = null;
        if (voucherMsg) {
          voucherMsg.style.color = "#db4156";
          voucherMsg.textContent = "Enter a voucher code";
        }
        return false;
      }
      var code = voucherInput.value.trim().toUpperCase();
      if (code === "CRUMBL10") {
        state.voucher = {
          code: code,
          amount_minor: Math.round(cartTotals().subtotal * 0.10),
        };
        if (voucherMsg) {
          voucherMsg.style.color = "#1a7f37";
          voucherMsg.textContent = "10% off applied";
        }
        return true;
      }
      state.voucher = null;
      if (voucherMsg) {
        voucherMsg.style.color = "#db4156";
        voucherMsg.textContent = "The code you entered was incorrect, please try again";
      }
      return false;
    }

    var applyBtn = form.querySelector("#apply-voucher");
    applyBtn.addEventListener("click", applyVoucher);
    form.querySelector("#voucher-code").addEventListener("input", clearVoucherMsg);

    var submit = el("button", "btn-pill btn-dark", "Continue to Review");
    submit.type = "submit";
    submit.addEventListener("click", function (event) {
      event.preventDefault();
      var name = form.querySelector("#contact-name");
      var ok = true;
      if (!name.value.trim()) { name.classList.add("field-error"); ok = false; }
      else name.classList.remove("field-error");
      if (MODE === "delivery") {
        var addr = form.querySelector("#delivery-address");
        if (!addr.value.trim()) { addr.classList.add("field-error"); ok = false; }
        else addr.classList.remove("field-error");
      }
      if (!ok) return;

      // Apply the voucher if one was typed but Apply wasn't pressed yet.
      var voucherInput = form.querySelector("#voucher-code");
      if (voucherInput && voucherInput.value.trim() && !state.voucher) {
        applyVoucher();
      }
      state.contact = {
        name: name.value.trim(),
        address: MODE === "delivery" ? form.querySelector("#delivery-address").value.trim() : null,
        time: MODE === "delivery" ? null : (form.querySelector("#pickup-time") || {}).value,
        note: (form.querySelector("#order-note") || {}).value || "",
      };
      state.step = "review"; saveState(); render();
    });
    form.appendChild(submit);

    body.innerHTML = "";
    body.appendChild(head);
    body.appendChild(form);
  }

  /* ---------------- review ---------------- */

  function renderReview(body) {
    var t = cartTotals();
    var head = el("div", "order-step-head", "<h1>Review Your Order</h1>");
    var card = el("div", "review-card", "");
    card.appendChild(el("h2", "", "Order Summary"));
    card.appendChild(el("div", "review-row", "<span>Store</span><strong>" + (state.store ? state.store.name : "") + "</strong>"));
    card.appendChild(el("div", "review-row", "<span>" + (MODE === "delivery" ? "Deliver to" : "Pickup for") + "</span><strong>" + (state.contact ? state.contact.name : "") + "</strong>"));
    if (state.contact && state.contact.address) {
      card.appendChild(el("div", "review-row", "<span>Address</span><strong>" + state.contact.address + "</strong>"));
    }
    if (state.contact && state.contact.time) {
      card.appendChild(el("div", "review-row", "<span>Time</span><strong>" + state.contact.time + "</strong>"));
    }
    if (state.contact && state.contact.note) {
      card.appendChild(el("div", "review-row", "<span>Note</span><strong>" + state.contact.note + "</strong>"));
    }
    state.cart.forEach(function (item) {
      card.appendChild(el("div", "review-row",
        "<span>" + item.box.name + " · " + item.flavors.length + " cookies</span><strong>" + cents(item.box.price) + "</strong>"));
    });
    card.appendChild(el("div", "review-row", "<span>Subtotal</span><strong>" + cents(t.subtotal) + "</strong>"));
    if (t.discount > 0) {
      card.appendChild(el("div", "review-row", "<span>Promo (" + state.voucher.code + ")</span><strong>-" + cents(t.discount) + "</strong>"));
    }
    card.appendChild(el("div", "review-row", "<span>Tax</span><strong>" + cents(t.tax) + "</strong>"));
    card.appendChild(el("div", "review-row", "<span>Tip</span><strong>" + cents(t.tip) + "</strong>"));
    card.appendChild(el("div", "review-row", "<span>Total</span><strong>" + cents(t.total) + "</strong>"));

    // Tip selection (source: "Select a tip amount").
    var tipCard = el("div", "review-card", "");
    tipCard.appendChild(el("h2", "", "Select a tip amount"));
    tipCard.appendChild(el("p", "", "Tips are appreciated, 100% of your tip will go to our hard-working bakers."));
    var tipOpts = el("div", "payment-options", "");
    [0, 100, 200, 300].forEach(function (amount) {
      var label = el("label", "payment-option", "");
      var checked = (state.tip || 0) === amount ? " checked" : "";
      label.innerHTML = "<input type='radio' name='tip' value='" + amount + "'" + checked + ">" +
        "<span>" + (amount === 0 ? "No tip" : cents(amount)) + "</span>";
      label.querySelector("input").addEventListener("change", function () {
        state.tip = amount;
        saveState(); render();
      });
      tipOpts.appendChild(label);
    });
    tipCard.appendChild(tipOpts);

    var nav = el("div", "step-nav", "");
    var back = el("button", "btn-pill btn-white", "Back");
    back.type = "button";
    back.addEventListener("click", function () { state.step = "checkout"; saveState(); render(); });
    nav.appendChild(back);
    var pay = el("button", "btn-pill btn-dark", "Continue to Payment");
    pay.type = "button";
    pay.setAttribute("data-testid", "continue-payment");
    pay.addEventListener("click", function () { state.step = "payment"; saveState(); render(); });
    nav.appendChild(pay);

    body.innerHTML = "";
    body.appendChild(head);
    body.appendChild(card);
    body.appendChild(tipCard);
    body.appendChild(nav);
  }

  /* ---------------- payment ---------------- */

  function renderPayment(body) {
    var t = cartTotals();
    var head = el("div", "order-step-head", "<h1>Tip &amp; Payment</h1>");
    var card = el("div", "review-card", "");
    card.appendChild(el("h2", "", "Total Due"));
    card.appendChild(el("div", "review-row", "<span>Order Total</span><strong data-testid='total-due'>" + cents(t.total) + "</strong>"));

    var pay = el("div", "payment-options", "");
    ["sandbox-approved", "sandbox-declined", "sandbox-retry"].forEach(function (scenario, i) {
      var label = el("label", "payment-option", "");
      label.innerHTML = "<input type='radio' name='scenario' value='" + scenario + "'" + (i === 0 ? " checked" : "") + ">" +
        "<span>" + (scenario === "sandbox-approved" ? "Simulated approval" : scenario === "sandbox-declined" ? "Simulated decline" : "Simulated retry") + "</span>";
      pay.appendChild(label);
    });

    var place = el("button", "btn-pill btn-dark", "Place Order");
    place.type = "button";
    place.setAttribute("data-testid", "place-order");
    place.addEventListener("click", function () {
      var scenario = (pay.querySelector("input[name='scenario']:checked") || {}).value || "sandbox-approved";
      place.disabled = true;
      place.textContent = "Placing order…";
      var payload = {
        mode: MODE,
        store_slug: state.store ? state.store.slug : null,
        items: state.cart.map(function (item) {
          return { box: item.box.id, flavors: item.flavors };
        }),
        contact: state.contact,
        voucher_code: state.voucher ? state.voucher.code : null,
        tip_minor: state.tip || 0,
        scenario_id: scenario,
      };
      fetch("/api/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok) throw new Error(data.error || "order failed");
          return data;
        });
      }).then(function (data) {
        state.order = data;
        state.step = "confirm";
        saveState(); render();
      }).catch(function (err) {
        place.disabled = false;
        place.textContent = "Try Again";
        var msg = el("p", "form-field error", "Sorry, there was an error placing this order: " + err.message);
        card.appendChild(msg);
      });
    });

    body.innerHTML = "";
    body.appendChild(head);
    body.appendChild(card);
    body.appendChild(pay);
    body.appendChild(place);
  }

  /* ---------------- confirmation ---------------- */

  function renderConfirm(body) {
    var order = state.order || {};
    var card = el("div", "confirm-card", "");
    card.setAttribute("data-testid", "order-confirmation");
    card.innerHTML = "<h1>Thank you for your order!</h1>" +
      "<p class='order-id'>Order ID: " + (order.order_id || "—") + "</p>" +
      "<p class='order-id' data-testid='receipt-id'>Receipt ID: " + (order.order_id || "—") + "</p>" +
      "<div class='summary'>" +
      "<div class='review-row'><span>" + (MODE === "delivery" ? "Delivery" : "Pickup") + " from</span><strong>" + (state.store ? state.store.name : "") + "</strong></div>" +
      "<div class='review-row'><span>Total paid</span><strong>" + cents(order.amount_minor || 0) + "</strong></div>" +
      "<div class='review-row'><span>Payment</span><strong>Simulated</strong></div>" +
      "</div>";
    var nav = el("div", "step-nav", "");
    var home = el("a", "btn-pill btn-white", "Back to Home");
    home.href = "/";
    nav.appendChild(home);
    var again = el("a", "btn-pill btn-dark", "Start An Order");
    again.href = "/order";
    nav.appendChild(again);
    var printBtn = el("button", "btn-pill btn-white", "Print Receipt");
    printBtn.type = "button";
    printBtn.addEventListener("click", function () { window.print(); });
    nav.appendChild(printBtn);

    body.innerHTML = "";
    body.appendChild(card);
    body.appendChild(nav);
    try { sessionStorage.removeItem("crumbl-order-" + MODE); } catch (e) {}
  }

  /* ---------------- boot ---------------- */

  loadState();
  if (state.step === "build" && !currentBox()) state.step = "store";
  var wrapper = el("div", "order-body", "");
  app.appendChild(wrapper);
  render();
})();
