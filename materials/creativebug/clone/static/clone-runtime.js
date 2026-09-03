/* creativebug 离线克隆运行时。
 *
 * 源站的 3664 个内联脚本与全部外链脚本在构建期已剔除（FAST-CLONE §4.5：
 * 行为等价，不是源码等价）。这里由克隆自己实现交互层，全部走同源 /api/*，
 * 不发任何跨域请求。
 */
(function () {
  "use strict";

  var api = {
    call: function (path, method, body) {
      return fetch(path, {
        method: method || "GET",
        credentials: "same-origin",
        headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          return { ok: r.ok, status: r.status, data: d };
        });
      });
    }
  };

  /* 会话状态只取一次，多个 hydrate 共用同一个 promise。
     此前 data-cb-auth 由 hydrateNav 的异步回调写入，而 hydrateRecommended
     在 boot() 里紧随其后同步读取该属性 —— 必然读到 null 而提前返回，
     登录后首页的推荐区块因此从来没有出现过。改为共享 promise 后不再有竞态。 */
  var _session = null;
  function session() {
    if (!_session) {
      _session = api.call("/api/session", "GET").then(function (res) {
        var on = !!(res.ok && res.data && res.data.authenticated);
        document.body.setAttribute("data-cb-auth", on ? "account" : "anonymous");
        return { ok: res.ok, on: on, data: res.data || {} };
      });
    }
    return _session;
  }

  /* 行内校验：必填为空时给出可见提示，而不是静默失败。
     对应 trace「必填字段为空或登出态发起动作时，行内校验指出要改什么」。 */
  function showFieldError(field, message) {
    var box = field.parentNode.querySelector(".cb-clone-error");
    if (!box) {
      box = document.createElement("div");
      box.className = "cb-clone-error";
      box.setAttribute("role", "alert");
      box.style.cssText = "color:#b00020;font:13px/1.4 system-ui;margin-top:4px";
      field.parentNode.appendChild(box);
    }
    box.textContent = message;
    field.setAttribute("aria-invalid", "true");
  }

  function clearFieldErrors(form) {
    form.querySelectorAll(".cb-clone-error").forEach(function (n) { n.remove(); });
    form.querySelectorAll("[aria-invalid]").forEach(function (n) {
      n.removeAttribute("aria-invalid");
    });
  }

  function validate(form) {
    clearFieldErrors(form);
    var ok = true;
    var fields = form.querySelectorAll("[required], input[type=email], input[type=password]");
    fields.forEach(function (f) {
      if (!String(f.value || "").trim()) {
        showFieldError(f, "This field is required.");
        ok = false;
      } else if (f.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.value)) {
        showFieldError(f, "Enter a valid email address.");
        ok = false;
      }
    });
    return ok;
  }

  /* 源站有些输入框没有 name 属性（首页那三个试用注册表单就是），
     FormData 只收有名字段，直接用它会提交出一个空对象 ——
     这正是"点了没反应"的那类死法。按 type/placeholder 推断键名补上。 */
  function inferName(el) {
    if (el.name) return el.name;
    var t = (el.type || "").toLowerCase();
    if (t === "email") return "email";
    if (t === "password") return "password";
    if (t === "tel") return "phone";
    var ph = (el.placeholder || "").toLowerCase();
    if (ph.indexOf("email") >= 0) return "email";
    if (ph.indexOf("password") >= 0) return "password";
    return null;
  }

  function formToObject(form) {
    var o = {};
    new FormData(form).forEach(function (v, k) { o[k] = v; });
    form.querySelectorAll("input, select, textarea").forEach(function (el) {
      if (el.name) return;                       // 已被 FormData 收走
      if (el.type === "submit" || el.type === "button") return;
      var k = inferName(el);
      if (k && !o[k] && el.value) o[k] = el.value;
    });
    return o;
  }

  /* 表单接线：data-cb-action 指明该表单调用哪个后端端点。
     构建期由 build_pages 在源站表单上补这个属性；这里只负责提交与回显。 */
  /* 源站的提交控件常常不是 type=submit：这个站的注册按钮是
     <button type="button" id="startSubscription">，靠源站 JS 绑 click。
     JS 按 §4.5 全部剔除后，只监听 submit 事件的话按钮点了毫无反应。
     AUTH-FLOW 第五步点名要求接住这类元素（含 div role="button"）。 */
  function wireTriggers(form) {
    var sel = 'button:not([type="submit"]), [role="button"], .cb-btn, .btn';
    form.querySelectorAll(sel).forEach(function (el) {
      if (el.getAttribute("data-cb-wired")) return;
      if (el.type === "submit") return;
      el.setAttribute("data-cb-wired", "1");
      el.addEventListener("click", function (e) {
        e.preventDefault();
        if (typeof form.requestSubmit === "function") {
          form.requestSubmit();
        } else {
          form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
        }
      });
    });
  }

  /* ---- 六位验证码落点 --------------------------------------------
     AUTH-FLOW §5 要求接通"六位码输入或邮件链接落点"，完成标准是
     "关键流程不依赖手工修改 cookie 或浏览器控制台"。

     此前 register/start 成功后只贴一句 "Check that address for a six-digit
     code."，页面上却没有任何地方能输入这个码 —— 用户在 Mailpit 里拿到码之后
     无路可走。注册与重置两条链路都缺这一步。 */

  var CHALLENGE = {
    registration: {
      action: "/api/auth/register/verify",
      title: "Enter your six-digit code",
      lead: "We emailed a six-digit code. Enter it below to finish creating your account.",
      submit: "Verify and continue",
      restart: "/api/auth/register/start",
      restartLabel: "Use a different email",
      password: false
    },
    reset: {
      action: "/api/auth/reset/complete",
      title: "Enter your six-digit code",
      lead: "We emailed a six-digit code. Enter it below and choose a new password.",
      submit: "Set new password",
      restart: "/api/auth/reset/start",
      restartLabel: "Send the code again",
      password: true
    }
  };

  function field(labelText, attrs) {
    var wrap = document.createElement("div");
    wrap.className = "cb-clone-field";
    wrap.style.cssText = "margin:0 0 12px";
    var label = document.createElement("label");
    label.textContent = labelText;
    label.style.cssText = "display:block;font:13px/1.6 system-ui;color:#444";
    var input = document.createElement("input");
    Object.keys(attrs).forEach(function (k) { input.setAttribute(k, attrs[k]); });
    input.style.cssText =
      "display:block;width:100%;max-width:320px;padding:8px 10px;font:16px system-ui;" +
      "border:1px solid #bbb;border-radius:3px";
    label.setAttribute("for", attrs.id);
    wrap.appendChild(label);
    wrap.appendChild(input);
    return { wrap: wrap, input: input };
  }

  /* 用验证码面板替换掉刚提交过的表单。email/password 留在闭包里，
     "换个邮箱/重发"要用它们重新发起挑战 —— 不写进 DOM，也不落 storage。 */
  function renderChallenge(anchor, kind, creds) {
    var spec = CHALLENGE[kind];
    if (!spec) return;
    if (document.querySelector(".cb-clone-challenge")) return;

    var box = document.createElement("section");
    box.className = "cb-clone-challenge";
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", spec.title);
    box.style.cssText =
      "margin:16px 0;padding:16px;border:1px solid #ddd;border-radius:4px;" +
      "background:#fff;max-width:420px";

    var h = document.createElement("h2");
    h.textContent = spec.title;
    h.style.cssText = "margin:0 0 6px;font:600 18px/1.3 system-ui;color:#222";
    var lead = document.createElement("p");
    lead.textContent = spec.lead;
    lead.style.cssText = "margin:0 0 14px;font:14px/1.5 system-ui;color:#555";
    box.appendChild(h);
    box.appendChild(lead);

    var code = field("Six-digit code", {
      type: "text", id: "cb-clone-code", name: "code", inputmode: "numeric",
      autocomplete: "one-time-code", maxlength: "6", pattern: "[0-9]{6}",
      placeholder: "000000", required: "required"
    });
    box.appendChild(code.wrap);

    var pw = null;
    if (spec.password) {
      pw = field("New password", {
        type: "password", id: "cb-clone-newpw", name: "password",
        autocomplete: "new-password", minlength: "8", required: "required",
        placeholder: "At least 8 characters"
      });
      box.appendChild(pw.wrap);
    }

    var err = document.createElement("div");
    err.className = "cb-clone-error";
    err.setAttribute("role", "alert");
    err.style.cssText = "color:#b00020;font:13px/1.4 system-ui;margin:0 0 10px;display:none";
    box.appendChild(err);

    function fail(msg) {
      err.textContent = msg;
      err.style.display = "block";
    }

    var go = document.createElement("button");
    go.type = "button";
    go.textContent = spec.submit;
    go.style.cssText =
      "padding:9px 16px;font:600 14px system-ui;color:#fff;background:#e2574c;" +
      "border:0;border-radius:3px;cursor:pointer";
    box.appendChild(go);

    var again = document.createElement("button");
    again.type = "button";
    again.textContent = spec.restartLabel;
    again.style.cssText =
      "margin-left:12px;padding:9px 4px;font:14px system-ui;color:#555;" +
      "background:none;border:0;text-decoration:underline;cursor:pointer";
    box.appendChild(again);

    go.addEventListener("click", function () {
      err.style.display = "none";
      var v = String(code.input.value || "").trim();
      if (!/^[0-9]{6}$/.test(v)) { fail("Enter the six digits from the email."); return; }
      var payload = { code: v };
      if (pw) {
        var np = String(pw.input.value || "");
        if (np.length < 8) { fail("Password must be at least 8 characters."); return; }
        payload.password = np;
      }
      go.disabled = true;
      api.call(spec.action, "POST", payload).then(function (res) {
        go.disabled = false;
        if (res.ok) {
          var bd = document.querySelector(".cb-clone-challenge-backdrop");
          if (bd) bd.remove();
          window.location.assign((res.data && res.data.redirect) || "/myclasses");
          return;
        }
        // 错误码、过期码、已用过的码都走这里，文案由服务端给
        fail((res.data && res.data.message) || "That code is not valid.");
      });
    });

    again.addEventListener("click", function () {
      err.style.display = "none";
      if (!creds || !creds.email) { window.location.assign("/trial/create-account"); return; }
      again.disabled = true;
      api.call(spec.restart, "POST", creds).then(function (res) {
        again.disabled = false;
        if (res.ok) { fail(""); err.style.display = "none"; code.input.value = ""; code.input.focus(); }
        else fail((res.data && res.data.message) || "Please try again in a moment.");
      });
    });

    /* 落点位置分两种：
       表单在模态框里时，把面板做成居中浮层 —— 否则藏掉 689px 高的表单只剩一个
       空模态壳，页面看起来像坏了（而且 focus() 还会把视口滚到那片空白上）。
       表单在正常内容流里时就地替换即可。 */
    var inModal = !!(anchor && anchor.closest &&
                     anchor.closest(".cb-modal, .modal, .modal-dialog"));
    if (inModal) {
      var back = document.createElement("div");
      back.className = "cb-clone-challenge-backdrop";
      back.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2147483646";
      box.style.cssText +=
        ";position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);" +
        "z-index:2147483647;box-shadow:0 8px 32px rgba(0,0,0,.25);width:min(420px,92vw)";
      document.body.appendChild(back);
      document.body.appendChild(box);
      if (anchor) anchor.style.display = "none";
      // 浮层里不要触发滚动，视口保持在用户原来的位置
      code.input.focus({ preventScroll: true });
      return;
    }
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(box, anchor);
      anchor.style.display = "none";
    } else {
      var m = contentMount();
      if (m) insertBelowHeader(m, box);   // 同样不能落进固定页头的盲区
    }
    code.input.focus({ preventScroll: true });
    box.scrollIntoView({ block: "center" });
  }

  /* 直接打开 ?step=verify 时也要有落点（register/start 的响应就指向这里）。 */
  function hydrateChallengeStep() {
    var step = new URLSearchParams(window.location.search).get("step");
    if (step !== "verify") return;
    var kind = /forgot|reset/.test(window.location.pathname) ? "reset" : "registration";
    var form = document.querySelector("form[data-cb-action^='/api/auth/']");
    renderChallenge(form, kind, null);
  }

  /* 登录后导航必须切到账户态。抓取件全是匿名外壳，所以每一页的页头都写死了
     Log In / Sign Up —— 登录之后回首页仍显示"登录"，与真实状态不符。 */
  function hydrateNav() {
    session().then(function (s) {
      if (!s.ok) return;
      if (!s.on) return;

      var RE_IN = /^\s*(log ?in|sign ?in|login|signin)\s*$/i;
      var RE_UP = /^\s*(sign ?up|start free trial|join now)\s*$/i;
      var nodes = document.querySelectorAll("header a, header button, header div[role=button], " +
                                            "nav a, nav button, nav div[role=button]");
      var swapped = false;
      Array.prototype.forEach.call(nodes, function (e) {
        var t = (e.textContent || "").trim();
        if (RE_IN.test(t)) {
          // 第一个登录入口就地变成"我的课程"，其余的隐藏，避免页头出现两个账户入口
          if (!swapped) {
            e.textContent = "My Classes";
            if (e.tagName === "A") e.setAttribute("href", "/myclasses");
            e.classList.add("cb-clone-account-link");
            swapped = true;
          } else {
            e.style.display = "none";
          }
        } else if (RE_UP.test(t)) {
          e.style.display = "none";
        }
      });

      // 退出入口：页面上没有就补一个，否则登录态无法从界面退出
      if (!document.querySelector("[data-cb-signout]")) {
        var host = document.querySelector(".cb-clone-account-link");
        if (host && host.parentNode) {
          var out = document.createElement("a");
          out.href = "#";
          out.textContent = "Log Out";
          out.setAttribute("data-cb-signout", "1");
          out.style.cssText = "margin-left:12px";
          out.addEventListener("click", function (ev) {
            ev.preventDefault();
            api.call("/api/auth/signout", "POST", {}).then(function () {
              window.location.assign("/");
            });
          });
          host.parentNode.insertBefore(out, host.nextSibling);
        }
      }
    });
  }

  /* ---- 源站内联处理器的本地实现 ------------------------------------
     抓取件保留了源站的 onclick="liopen(...)" 等内联调用，而源站脚本已被剥离，
     于是这些控件点下去抛 ReferenceError。实测（抽 60 页，只数可见且函数未定义的）：
       liopen 120 个 / enlarge 8 / thumbRate 6 —— 且**没有一个**有 <a href> 兜底。
     这里按行为等价重新实现，挂到 window 上让既有内联调用能解析。
     `ga` 是源站埋点，不实现 —— 复现它反而违反离线轴；未定义即不发包。 */

  function _closestLi(el) {
    while (el && el.tagName !== "LI") el = el.parentElement;
    return el;
  }

  /* 侧栏子菜单展开：源站是 <li> 内的子列表折叠 */
  window.liopen = function (id) {
    var host = null;
    if (id) host = document.getElementById(id);
    if (!host && window.event && window.event.target) host = _closestLi(window.event.target);
    if (!host) return false;
    var sub = host.querySelector("ul, .sub, .submenu") || host.nextElementSibling;
    if (!sub) return false;
    var open = sub.getAttribute("data-cb-open") === "1";
    sub.setAttribute("data-cb-open", open ? "0" : "1");
    sub.style.display = open ? "none" : "block";
    host.setAttribute("aria-expanded", String(!open));
    return false;
  };

  /* 图片放大：源站是灯箱。这里用一个同源的覆盖层，不引入任何外部依赖。 */
  window.enlarge = function (src) {
    var img = null;
    if (typeof src === "string" && src) {
      img = src;
    } else if (window.event && window.event.target) {
      var t = window.event.target;
      var found = t.tagName === "IMG" ? t : t.querySelector && t.querySelector("img");
      if (!found && t.parentElement) found = t.parentElement.querySelector("img");
      img = found && (found.getAttribute("data-full") || found.src);
    }
    if (!img) return false;
    var back = document.createElement("div");
    back.className = "cb-clone-lightbox";
    back.setAttribute("role", "dialog");
    back.setAttribute("aria-label", "Enlarged image");
    back.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:2147483647;" +
      "display:flex;align-items:center;justify-content:center;cursor:zoom-out";
    var big = document.createElement("img");
    big.src = img;
    big.alt = "";
    big.style.cssText = "max-width:92vw;max-height:92vh;box-shadow:0 8px 40px rgba(0,0,0,.5)";
    back.appendChild(big);
    function close() {
      back.remove();
      document.removeEventListener("keydown", onKey);
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    back.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(back);
    return false;
  };

  /* 评分拇指：状态由服务端返回后再渲染，与 wireStateButtons 同一口径 */
  window.thumbRate = function (classId, up) {
    var target = window.event && window.event.target;
    var cid = classId || (target && target.getAttribute &&
                          target.getAttribute("data-cb-class"));
    if (!cid) return false;
    api.call("/api/rating", "POST", { class_id: cid, stars: up === false ? 1 : 5 })
      .then(function (res) {
        if (target && target.setAttribute) {
          target.setAttribute("aria-pressed", String(!!res.ok));
        }
        if (!res.ok && res.status === 401) {
          window.location.assign("/trial/create-account");
        }
      });
    return false;
  };

  /* 登录后首页的「Recommended for you」。
     用户 2026-08-30 裁定：此处不要求与源站逐项对应，用库里**页面完整**的课来填，
     目的是登录后有可点、点进去有内容。数据来自同源 /api/search，不外发请求。 */
  function hydrateRecommended() {
    if (!/^\/$/.test(window.location.pathname)) return;
    if (document.querySelector(".cb-clone-recommended")) return;
    var mount = contentMount();
    if (!mount) return;

    session().then(function (s) {
      if (!s.on) return null;
      return api.call("/api/search?q=&level=beginner", "GET");
    }).then(function (res) {
      if (!res || !res.ok) return;
      var list = (res.data && res.data.results || []).slice(0, 8);
      if (!list.length) return;
      var sec = document.createElement("section");
      sec.className = "cb-clone-recommended";
      sec.style.cssText = "margin:24px 0;padding:0 16px";
      var h = document.createElement("h2");
      h.textContent = "Recommended for you";
      h.style.cssText = "margin:0 0 12px;font:600 20px/1.3 system-ui;color:#222";
      sec.appendChild(h);
      var row = document.createElement("div");
      row.style.cssText = "display:flex;flex-wrap:wrap;gap:16px";
      list.forEach(function (c) {
        var card = document.createElement("a");
        card.href = c.route || "#";
        card.className = "cb-clone-rec-card";
        card.setAttribute("data-cb-class", c.class_id);
        card.style.cssText =
          "flex:0 0 calc(25% - 12px);min-width:200px;text-decoration:none;color:inherit";
        var t = document.createElement("div");
        t.textContent = c.title || c.class_id;
        t.style.cssText = "font:600 14px/1.35 system-ui;margin-bottom:4px";
        var m = document.createElement("div");
        m.textContent = [c.instructor, c.level].filter(Boolean).join(" \u00b7 ");
        m.style.cssText = "font:12px system-ui;color:#666";
        card.appendChild(t); card.appendChild(m);
        row.appendChild(card);
      });
      sec.appendChild(row);
      insertBelowHeader(mount, sec);
    });
  }

  /* 首页评论卡片：源站是可切换的一组，抓取件里只留下静态几张。
     补上切换（上一张/下一张 + 圆点），只操作页面上已有的卡片，不造评论内容。 */
  function wireTestimonialCarousel() {
    var cards = [].slice.call(document.querySelectorAll(
      ".testimonial, .testimonial-card, [class*='testimonial']"))
      .filter(function (e) { return e.querySelector("p, blockquote"); });
    if (cards.length < 2) return;
    if (document.querySelector(".cb-clone-testimonial-nav")) return;

    var idx = 0;
    function show(i) {
      idx = (i + cards.length) % cards.length;
      cards.forEach(function (c, n) { c.style.display = n === idx ? "" : "none"; });
      [].slice.call(nav.querySelectorAll("[data-dot]")).forEach(function (d, n) {
        d.style.background = n === idx ? "#e2574c" : "#ccc";
      });
    }
    var nav = document.createElement("div");
    nav.className = "cb-clone-testimonial-nav";
    nav.style.cssText = "display:flex;gap:8px;align-items:center;justify-content:center;margin:12px 0";
    function btn(label, delta) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.setAttribute("aria-label", delta < 0 ? "Previous testimonial" : "Next testimonial");
      b.style.cssText = "border:0;background:none;font:16px system-ui;cursor:pointer;padding:4px 8px";
      b.addEventListener("click", function () { show(idx + delta); });
      return b;
    }
    nav.appendChild(btn("\u2039", -1));
    cards.forEach(function (_, n) {
      var d = document.createElement("button");
      d.type = "button"; d.setAttribute("data-dot", String(n));
      d.setAttribute("aria-label", "Testimonial " + (n + 1));
      d.style.cssText = "width:8px;height:8px;border-radius:50%;border:0;cursor:pointer;background:#ccc";
      d.addEventListener("click", function () { show(n); });
      nav.appendChild(d);
    });
    nav.appendChild(btn("\u203a", 1));
    cards[0].parentNode.insertBefore(nav, cards[0].nextSibling);
    show(0);
  }

  /* 被替换过落点的卡片：把卡片上显示的内容改成**落点那门课**的。
     源站目标未采集时链接会改投到另一门真实的课；如果卡片仍显示原来那门课的
     标题，就成了"说一套跳一套"。这里在渲染后的 DOM 上按 data-cb-substituted
     标记逐个校正，只改文字，不动嵌套结构。 */
  /* 落点课程的缩略图：构建期由 tools/gen_class_thumbnails.py 生成，
     只收未被改投的真实卡片上的图。没有覆盖到的课程回退成"藏图"。 */
  function _classThumbs() {
    return fetch("/static/class-thumbnails.json", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });
  }

  function realignSubstitutedCards() {
    var marked = [].slice.call(document.querySelectorAll("[data-cb-substituted]"));
    if (!marked.length) return;

    var wanted = {};
    marked.forEach(function (a) { wanted[a.getAttribute("data-cb-substituted")] = 1; });

    Promise.all([api.call("/api/search?q=&limit=2000", "GET"), _classThumbs()])
      .then(function (both) {
      var res = both[0], thumbs = both[1] || {};
      if (!res.ok) return;
      var byRoute = {};
      (res.data && res.data.results || []).forEach(function (c) {
        if (c.route) byRoute[c.route.replace(/\/+$/, "")] = c;
      });

      marked.forEach(function (a) {
        var info = byRoute[(a.getAttribute("data-cb-substituted") || "").replace(/\/+$/, "")];
        if (!info) return;

        // 卡片的标题/讲师通常是链接的兄弟节点，不在 <a> 里面。
        // 从链接往上找到最近的卡片容器，再在容器内校正文字。
        // 找卡片容器：按文字量收敛。固定层数的爬法会冲出卡片，落到含导航和
        // 登录提示的大容器上（实测爬 4~5 层就越界）。卡片本身文字很少，
        // 一旦容器文字量变大就说明已经越界，停在上一层。
        // 优先用轮播条目本身作为卡片边界（related classes 用的是 .slick-item），
        // 找不到再退回"按文字量收敛"。固定层数的爬法会冲出卡片。
        var best = a.closest ? a.closest(".slick-item, .card, .workshop-card, li") : null;
        if (!best || (best.textContent || "").trim().length > 260) {
          var card = a;
          best = null;
          for (var i = 0; i < 5 && card.parentElement; i++) {
            card = card.parentElement;
            var len = (card.textContent || "").trim().length;
            if (len > 220) break;
            if (len > 3) best = card;
          }
        }
        if (!best) return;
        /* 标题是一个 <a>，不是 p/span/div —— 旧的候选选择器只找后三者，
           于是标题从来没被改写过：卡片停在"旧标题 + 藏掉的图 + 指向另一门课"。
           这里按"与卡片同 href、不含 <img>、有文字"来认标题锚点。 */
        var titleEl = best.querySelector(".card-title, h3, h4, h5, .workshop-title, .title");
        if (!titleEl) {
          var href = a.getAttribute("href");
          titleEl = [].slice.call(best.querySelectorAll("a[href]")).filter(function (e) {
            return e.getAttribute("href") === href && !e.querySelector("img") &&
                   (e.textContent || "").trim().length > 6;
          })[0];
        }
        /* 卡片上写的是课名，info.title 是"课名 by 讲师"，拆开用 */
        var full = info.title || "";
        var cut = full.lastIndexOf(" by ");
        var courseName = cut > 0 ? full.slice(0, cut) : full;
        var personName = cut > 0 ? full.slice(cut + 4) : "";
        if (titleEl && courseName) titleEl.textContent = courseName;

        var who = best.querySelector(".instructor, .card-instructor, .by");
        if (who && info.instructor) who.textContent = info.instructor;
        var whoLink = best.querySelector(".instructor-link");
        if (whoLink && personName) whoLink.textContent = personName;

        /* 图：优先换成落点课程自己的图，卡片三要素就与落点一致了。
           没有登记缩略图的（302/465 有）才回退成藏起来 ——
           不留一张属于另一门课的图。 */
        var newSrc = thumbs[(a.getAttribute("data-cb-substituted") || "").replace(/\/+$/, "")];
        [].slice.call(best.querySelectorAll("img")).forEach(function (im) {
          if (im.getAttribute("data-cb-kept")) return;
          if (im.classList.contains("profile-img") || im.classList.contains("instructor-img")) return;
          if (newSrc) {
            im.setAttribute("src", newSrc);
            im.setAttribute("alt", courseName || "");
            im.style.visibility = "";
          } else {
            im.style.visibility = "hidden";
          }
        });

        a.setAttribute("title", info.title || "");
        a.setAttribute("aria-label", info.title || "");
      });
    });
  }

  function wireForms() {
    document.querySelectorAll("form[data-cb-action]").forEach(function (form) {
      wireTriggers(form);
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        if (!validate(form)) return;
        var btn = form.querySelector("[type=submit]");
        if (btn) btn.disabled = true;
        api.call(form.getAttribute("data-cb-action"), "POST", formToObject(form))
          .then(function (res) {
            if (btn) btn.disabled = false;
            if (res.ok && res.data.redirect) {
              window.location.assign(res.data.redirect);
            } else if (!res.ok) {
              var first = form.querySelector("input,select,textarea");
              if (first) showFieldError(first, res.data.message || "That did not work. Please try again.");
            } else if (res.data.message) {
              var note = document.createElement("div");
              note.className = "cb-clone-notice";
              note.setAttribute("role", "status");
              note.textContent = res.data.message;
              form.appendChild(note);
              // 服务端说"去查邮件拿六位码"时，必须同时给出输入这个码的地方，
              // 否则用户拿到码之后无路可走（正是此前的状况）。
              var act = form.getAttribute("data-cb-action") || "";
              var kind = act.indexOf("/api/auth/register/") === 0 ? "registration"
                       : act.indexOf("/api/auth/reset/") === 0 ? "reset" : null;
              var wantsCode = /six-digit|reset code/i.test(res.data.message) ||
                              /step=verify/.test(res.data.next || "");
              if (kind && wantsCode) {
                var sent = formToObject(form);
                renderChallenge(form, kind,
                  sent.email ? { email: sent.email, password: sent.password } : null);
              }
            }
          });
      });
    });
  }

  /* 收藏 / 报名 / 进度：状态一律由服务端返回后再渲染，
     对应不变量 progress-server-authoritative（客户端不得自行认定状态）。 */
  /* /myclasses 的已报名列表。抓取时账号还没有任何课程，采到的是空状态外壳，
     #fragment-content 是源站注入列表的位置。接口早就返回数据，页面却一直空着 ——
     接口通不等于页面上看得见，这里补上渲染。 */
  /* 挂载点必须是主内容流里"看得见"的容器。
     #fragment-content 在源站是 offcanvas 面板里的空 div，尺寸为 0 ——
     往那里塞内容，DOM 里查得到，页面上一个字也看不见。 */
  function contentMount() {
    var cands = [document.getElementById("main"),
                 document.querySelector("section#main"),
                 document.getElementById("main-content")];
    for (var i = 0; i < cands.length; i++) {
      var e = cands[i];
      if (e && e.getBoundingClientRect().width > 0) return e;
    }
    return document.getElementById("fragment-content");
  }

  /* 源站页头 #header_wrapper 是 position:fixed（视口 y 50~150），而 #main 从
     y=50 起算 —— 也就是说 #main 顶部约 100px 一直压在页头底下，源站靠首屏
     Banner 顶着这段空档。注入的区块若直接 prepend 到 #main，就会落进这段
     盲区：看得见一半，点又点不中（elementFromPoint 命中的是页头）。
     所以插入点要跳过被固定页头覆盖的那几个子节点。 */
  function headerBottom() {
    var h = document.getElementById("header_wrapper");
    if (!h) h = document.querySelector("header");
    if (!h) return 0;
    if (getComputedStyle(h).position !== "fixed") return 0;
    var r = h.getBoundingClientRect();
    return r.top + r.height;          // 视口坐标；载入时 scrollY=0，即文档坐标
  }

  function insertBelowHeader(mount, el) {
    var limit = headerBottom();
    el.style.scrollMarginTop = Math.round(limit + 16) + "px";
    /* 必须插在某个"可见且底边已越过页头"的兄弟**之后**：
       插在它之前不管用 —— #main 开头是一串 0 高度的 <style>，
       插进去仍然是整段内容的第一个可见元素，照样压在页头底下。 */
    var kids = mount.children;
    for (var i = 0; i < kids.length; i++) {
      var r = kids[i].getBoundingClientRect();
      if (r.height > 0 && r.top + scrollY + r.height >= limit) {
        mount.insertBefore(el, kids[i].nextSibling);
        return true;
      }
    }
    mount.appendChild(el);
    return true;
  }

  function mountBlock(el) {
    var m = contentMount();
    if (!m) return false;
    return insertBelowHeader(m, el);
  }

  function hydrateMyClasses() {
    if (!/^\/myclasses\/?$/.test(window.location.pathname)) return;
    var mount = document.createElement("section");
    mount.className = "cb-clone-myclasses";
    if (!mountBlock(mount)) return;
    api.call("/api/myclasses", "GET").then(function (res) {
      if (!res.ok) return;
      var list = (res.data && res.data.classes) || [];
      if (!list.length) {
        var empty = document.createElement("div");
        empty.className = "cb-clone-empty";
        empty.setAttribute("role", "status");
        empty.textContent = "You haven't started any classes yet.";
        var browse = document.createElement("a");
        browse.href = "/classes";
        browse.textContent = "Browse classes";
        empty.appendChild(document.createTextNode(" "));
        empty.appendChild(browse);
        mount.appendChild(empty);
        return;
      }
      var row = document.createElement("div");
      row.className = "row card-row";
      list.forEach(function (c) {
        var col = document.createElement("div");
        col.className = "col-4 card";
        var a = document.createElement("a");
        a.href = c.route || "#";
        a.className = "card-title";
        a.textContent = c.title || c.class_id;
        a.setAttribute("data-cb-class", c.class_id);
        var meta = document.createElement("p");
        meta.className = "card-text";
        var total = c.unit_count || 1;
        var done = c.watched_units || 0;
        meta.textContent = (c.track === "audit" ? "Auditing" : "Enrolled") +
          " \u00b7 " + done + "/" + total + " lessons watched";
        col.appendChild(a);
        col.appendChild(meta);
        row.appendChild(col);
      });
      mount.appendChild(row);
    });
  }

  /* 搜索结果页。服务端在 /search/ui 注入 window.__cbSearch，但此前没有任何
     代码消费它 —— 回车之后落到通用目录页，既没有结果也没有"无结果"提示。 */
  function hydrateSearch() {
    var q = (window.__cbSearch || {}).q;
    if (typeof q !== "string") return;
    var mount = document.createElement("section");
    mount.className = "cb-clone-search";
    if (!mountBlock(mount)) return;
    api.call("/api/search?q=" + encodeURIComponent(q), "GET").then(function (res) {
      if (!res.ok) return;
      var d = res.data || {};
      var list = d.results || [];
      var head = document.createElement("h2");
      head.className = "cb-clone-search-head";
      head.textContent = list.length
        ? list.length + " results for \u201c" + q + "\u201d"
        : "No classes match \u201c" + q + "\u201d";
      mount.appendChild(head);
      if (!list.length) {
        var note = document.createElement("div");
        note.className = "cb-clone-empty";
        note.setAttribute("role", "status");
        var es = d.empty_state || {};
        note.textContent = es.message || "No classes match that search.";
        var back = document.createElement("a");
        back.href = es.route_back || "/classes";
        back.textContent = "Browse all classes";
        note.appendChild(document.createTextNode(" "));
        note.appendChild(back);
        mount.appendChild(note);
        return;
      }
      var row = document.createElement("div");
      row.className = "row card-row";
      list.forEach(function (c) {
        var col = document.createElement("div");
        col.className = "col-4 card";
        var a = document.createElement("a");
        a.href = c.route || "#";
        a.className = "card-title";
        a.textContent = c.title || c.class_id;
        a.setAttribute("data-cb-class", c.class_id);
        var meta = document.createElement("p");
        meta.className = "card-text";
        meta.textContent = [c.instructor, c.level,
          c.duration_minutes ? c.duration_minutes + " min" : null]
          .filter(Boolean).join(" \u00b7 ");
        col.appendChild(a);
        col.appendChild(meta);
        row.appendChild(col);
      });
      mount.appendChild(row);
    });
  }

  function wireStateButtons() {
    document.querySelectorAll("[data-cb-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        btn.disabled = true;
        api.call(btn.getAttribute("data-cb-toggle"), "POST",
                 { class_id: btn.getAttribute("data-cb-class") })
          .then(function (res) {
            btn.disabled = false;
            if (res.status === 401) {
              window.location.assign("/trial/create-account?next=" +
                encodeURIComponent(window.location.pathname));
              return;
            }
            if (res.ok) {
              btn.setAttribute("aria-pressed", String(!!res.data.active));
              if (res.data.label) btn.textContent = res.data.label;
            }
          });
      });
    });
  }

  /* 播放器占位：视频内容按口径 7 不复刻，但进度接口仍然真实存在，
     点击即向服务端记一次进度，使 lesson-progress 那条 journey 可完成。 */
  function wirePlayerPlaceholders() {
    document.querySelectorAll(".cb-clone-player-placeholder").forEach(function (el) {
      el.addEventListener("click", function () {
        var cls = el.getAttribute("data-cb-class");
        var unit = el.getAttribute("data-cb-unit");
        if (!cls) return;
        api.call("/api/progress", "POST", { class_id: cls, unit_id: unit, watched: true })
          .then(function (res) {
            if (res.ok) el.setAttribute("data-cb-progress", "recorded");
          });
      });
    });
  }

  /* 模态框：源站用自写 JS 控制显隐，JS 按 §4.5 剔除后登录入口点了毫无反应。
     这里由克隆自己显式控制，不去猜源站的 CSS 机制 —— 已记入 known-differences。 */
  function showModal(el) {
    if (!el) return;
    el.style.display = "block";
    el.classList.add("in", "cb-clone-open");
    el.setAttribute("aria-hidden", "false");
    if (!document.querySelector(".cb-clone-backdrop")) {
      var bd = document.createElement("div");
      bd.className = "cb-clone-backdrop";
      bd.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:11999";
      bd.addEventListener("click", function () { hideModal(el); });
      document.body.appendChild(bd);
    }
    var first = el.querySelector("input:not([type=hidden])");
    if (first) first.focus();
  }

  function hideModal(el) {
    if (!el) return;
    el.style.display = "none";
    el.classList.remove("in", "cb-clone-open");
    el.setAttribute("aria-hidden", "true");
    var bd = document.querySelector(".cb-clone-backdrop");
    if (bd) bd.remove();
  }

  function wireModals() {
    // 源站的登录入口是 <a class="js-login"> —— 没有 href，全靠 JS 绑定
    document.querySelectorAll(".js-login, .js-login-init, [data-cb-open-modal]").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        var id = el.getAttribute("data-cb-open-modal") || "cb_login_modal";
        showModal(document.getElementById(id));
      });
    });
    // 侧边栏里那个 li 用 inline onclick 触发 .js-login，jQuery 没了也要能用
    document.querySelectorAll('[onclick*="js-login"]').forEach(function (el) {
      el.removeAttribute("onclick");
      el.addEventListener("click", function (e) {
        e.preventDefault();
        showModal(document.getElementById("cb_login_modal"));
      });
    });
    document.querySelectorAll('[data-dismiss="modal"], .cb-modal .close').forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        var m = el.closest(".modal, .cb-modal");
        hideModal(m);
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        document.querySelectorAll(".cb-clone-open").forEach(hideModal);
      }
    });
    /* 初始状态：由触发器驱动的模态框关闭。
       但有的页面（/trial/create-account）把模态框内容当作页面主表单展示，
       构建期给它打了 data-cb-inline —— 那种不能藏，藏了用户就没有输入框了。 */
    document.querySelectorAll("#cb_login_modal, .cb-modal").forEach(function (el) {
      if (el.getAttribute("data-cb-inline")) {
        /* 内联模态框：只是"不主动隐藏"不够。Bootstrap 自带 .modal{display:none}
           —— 早期 CDN 版被剔除时看不出来，把 Bootstrap 本地化以修复本页栅格塌陷
           之后，这条规则又把表单藏了回去。这里必须主动显形，并把 .modal 的
           fixed 全屏定位改回文档流，否则表单会盖住整页。 */
        el.style.setProperty("display", "block", "important");
        el.style.setProperty("position", "static", "important");
        el.style.setProperty("overflow", "visible", "important");
        el.style.setProperty("z-index", "auto", "important");
        el.setAttribute("aria-hidden", "false");
        el.querySelectorAll(".modal-dialog").forEach(function (d) {
          d.style.setProperty("margin", "0 auto", "important");
          d.style.setProperty("width", "100%", "important");
        });
        return;
      }
      if (!el.classList.contains("cb-clone-open")) el.style.display = "none";
    });
  }

  /* 源站靠 jQuery 内联 handler 实现的几个常见交互，构建期已把 handler 剥掉，
     这里用原生事件重新实现。行为等价，不追求源码等价（§4.5）。 */
  function wireCommonInteractions() {
    // 侧边栏开关
    document.querySelectorAll(".js-sidebar-toggle, .navbar-toggle, .menu-toggle").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        document.documentElement.classList.toggle("sidebar-open");
      });
    });
    // 搜索框：回车提交
    document.querySelectorAll('form input[type="text"], form input[type="search"]').forEach(function (el) {
      el.addEventListener("keypress", function (e) {
        if (e.key !== "Enter") return;
        var f = el.closest("form");
        if (!f) return;
        e.preventDefault();
        if (f.getAttribute("data-cb-action")) {
          f.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
        } else {
          f.submit();
        }
      });
    });
    // 迷你搜索框 → 展开完整搜索
    var mini = document.getElementById("mini_topnav_search");
    var full = document.getElementById("topnav_search");
    if (mini && full) {
      mini.addEventListener("click", function () {
        mini.style.display = "none";
        full.style.display = "";
        var box = document.getElementById("full-search-box");
        if (box) box.focus();
      });
    }
  }

  /* 源站的轮播图走 Slick 的 data-lazy：真正的 src 由 Slick 在滑到该帧时写入。
     §4.5 把 JS 全剥掉之后没人做这件事 —— 全站 608 个页面、10912 张图永远空白，
     而资产其实早就抓好、本地化好躺在 static/assets 里了。
     这里用原生代码补上同样的效果（行为等价，不追求源码等价）。

     不用 IntersectionObserver：轮播容器 overflow:hidden，非首帧被祖先裁掉，
     观察器判定为不相交；而轮播的翻页 JS 同样已被剥掉，用户永远翻不过去，
     那些帧就会永久空白。每页中位 19 张、最多 29 张，直接加载代价可以接受。 */
  function hydrateLazyImages() {
    document.querySelectorAll("img[data-lazy]").forEach(function (img) {
      var u = img.getAttribute("data-lazy");
      if (!u || img.getAttribute("src")) return;   // 已有真 src 的不覆盖
      img.setAttribute("src", u);
      img.classList.remove("slick-loading");
    });
  }


  /* ------------------------------------------------------------------
     源站内联 handler 的接住层。

     抓取件保留了源站的 onclick/onmouseover，它们调用源站 JS 里的全局函数。
     §4.5 把源站脚本整体剔除后，这些函数没有定义：点一下抛 ReferenceError，
     控件表面看着在、其实是死的。独立审阅实测：1009/1010 页至少有一处。

     判据：凡"点了应该有反应"的，在这里用同源实现补上；
     凡源站发往第三方的（分析埋点），补成 no-op —— 它们必须不发请求。
     需要服务端持久化而本站没有对应端点的（笔记、通知、评论），
     实现为仅本次会话有效，并已在 known-differences 里声明。
     ------------------------------------------------------------------ */

  function _evtTarget(el) {
    if (el && el.nodeType === 1) return el;
    return (window.event && window.event.target) || null;
  }
  function _up(el, test) {
    while (el && el.nodeType === 1) { if (test(el)) return el; el = el.parentElement; }
    return null;
  }

  /* 导航悬停：CSS 已有 `li:hover+.submenu` 兜底，桌面鼠标本来就能展开。
     源站另有 `.on` 一路（触屏/键盘），这里补上并保持同层互斥。 */
  window.sel = function (el) {
    var li = _up(_evtTarget(el), function (n) { return n.tagName === "LI"; });
    if (!li || !li.parentElement) return false;
    var sibs = li.parentElement.children;
    for (var i = 0; i < sibs.length; i++) {
      if (sibs[i] !== li) sibs[i].classList.remove("on");
    }
    li.classList.add("on");
    return false;
  };

  /* 评论排序。源站按 data-url 拉服务端分页；本站评论已全部在 DOM 里，
     因此就地重排：most_recent 还原原始顺序，另两个按星级。
     星级取 .star-ratings-css-top 的宽度百分比 —— 那就是源站画星星的方式。 */
  function _reviewItems() {
    var thumbs = document.querySelectorAll(".review_thumbs");
    var items = [];
    for (var i = 0; i < thumbs.length; i++) {
      var el = thumbs[i];
      while (el.parentElement &&
             el.parentElement.querySelectorAll(".review_thumbs").length === 1) {
        el = el.parentElement;
      }
      if (el.parentElement) items.push(el);
    }
    return items;
  }
  function _ratingOf(node) {
    var top = node.querySelector(".star-ratings-css-top");
    if (!top) return 0;
    var m = /width:\s*([\d.]+)%/.exec(top.getAttribute("style") || "");
    return m ? parseFloat(m[1]) : 0;
  }
  window.orderReviews = function (el) {
    var a = _up(_evtTarget(el), function (n) { return n.hasAttribute && n.hasAttribute("data-sort"); });
    if (!a) return false;
    var sort = a.getAttribute("data-sort");
    var items = _reviewItems();
    if (!items.length) return false;
    var parent = items[0].parentElement;

    if (!parent.hasAttribute("data-cb-order")) {
      for (var i = 0; i < items.length; i++) items[i].setAttribute("data-cb-idx", String(i));
      parent.setAttribute("data-cb-order", "1");
    }
    var arr = items.slice();
    if (sort === "highest_rated") {
      arr.sort(function (x, y) { return _ratingOf(y) - _ratingOf(x); });
    } else if (sort === "lowest_rated") {
      arr.sort(function (x, y) { return _ratingOf(x) - _ratingOf(y); });
    } else {
      arr.sort(function (x, y) {
        return (+x.getAttribute("data-cb-idx")) - (+y.getAttribute("data-cb-idx"));
      });
    }
    for (var j = 0; j < arr.length; j++) parent.appendChild(arr[j]);

    /* 按钮回显与勾选标记，跟源站一致 */
    var menu = _up(a, function (n) { return n.classList && n.classList.contains("dropdown-menu"); });
    if (menu) {
      var links = menu.querySelectorAll("[data-sort]");
      for (var k = 0; k < links.length; k++) {
        var ok = links[k].querySelector(".glyphicon-ok");
        if (ok) ok.style.color = links[k] === a ? "" : "transparent";
      }
      var btn = menu.parentElement && menu.parentElement.querySelector("button");
      if (btn) btn.textContent = (a.textContent || "").trim();
    }
    return false;
  };

  /* 站点促销条的 [X]。源站这个函数名叫 openPanel，做的是收起。 */
  window.openPanel = function () {
    var bar = document.querySelector(".sitewide-promo-footer");
    if (bar) bar.style.display = "none";
    return false;
  };

  window.topFunction = function () {
    try { window.scrollTo({ top: 0, behavior: "smooth" }); }
    catch (e) { window.scrollTo(0, 0); }
    return false;   /* 源站这个 <a href="">，不拦会整页重载 */
  };

  window.scrollToDownloads = function () {
    /* 这个 onclick 与 data-toggle="tab" 挂在同一个 <a> 上，内联先跑、
       页签切换在冒泡阶段后跑；不延后就会滚向一个还是 display:none 的面板。 */
    setTimeout(function () {
      var t = document.getElementById("materials") ||
              document.querySelector("[id*='material'], .downloads");
      if (t && t.scrollIntoView) t.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
    return undefined;   /* 不能 return false —— 那会连页签切换一起拦掉 */
  };

  window.expandReplies = function (id) {
    var host = (id != null && document.getElementById("expand-replies-" + id)) ||
               _up(_evtTarget(null), function (n) {
                 return n.classList && n.classList.contains("expand-replies");
               });
    if (!host) return false;
    /* 回复挂在 #replies-<id>，不是相邻兄弟节点 */
    var box = (id != null && document.getElementById("replies-" + id)) ||
              host.parentElement.querySelector("[id^='replies-'], .replies");
    if (!box) return false;
    var open = host.getAttribute("data-cb-open") === "1";
    host.setAttribute("data-cb-open", open ? "0" : "1");
    box.style.display = open ? "none" : "block";
    return false;
  };

  /* 复制分享链接。源站用的是第三方剪贴板库；这里用原生 API，
     不可用时退回选中文本，让用户自己 Ctrl-C。 */
  window.myFunction = function () {
    var input = document.querySelector("#share-watchlist-url, [id^='share-'][id$='-url']");
    if (!input) return false;
    input.select();
    var done = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(input.value); done = true;
      } else { done = document.execCommand("copy"); }
    } catch (e) { done = false; }
    var btn = _evtTarget(null);
    if (btn && btn.tagName === "BUTTON") {
      var old = btn.textContent;
      btn.textContent = done ? "Copied" : "Press Ctrl+C";
      setTimeout(function () { btn.textContent = old; }, 1600);
    }
    return false;
  };

  /* --- 评论区：源站有服务端，本站没有对应端点。
         按 known-differences::comment_actions_are_session_only 处理：
         界面照常反应，但不跨请求持久化。 --- */
  window.likeComment = function (cls) {
    var node = (typeof cls === "string" && document.querySelector("." + cls.replace(/[^\w-]/g, ""))) ||
               _up(_evtTarget(null), function (n) { return n.classList && n.classList.contains("like"); });
    if (!node) return false;
    var on = node.getAttribute("data-cb-liked") === "1";
    node.setAttribute("data-cb-liked", on ? "0" : "1");
    node.classList.toggle("selected", !on);
    var tot = node.querySelector(".likes-total");
    if (tot) {
      var n = parseInt((tot.textContent || "0").trim(), 10) || 0;
      tot.textContent = " " + (on ? Math.max(0, n - 1) : n + 1) + " ";
    }
    var st = node.querySelector(".state-text");
    if (st) st.textContent = on ? "" : "Liked";
    return false;
  };

  window.clickReply = function (id) {
    var nav = _up(_evtTarget(null), function (n) {
      return n.classList && n.classList.contains("comment-nav");
    });
    if (!nav) return false;
    var existing = nav.parentElement.querySelector(".cb-clone-replybox");
    if (existing) { existing.remove(); return false; }
    var box = document.createElement("div");
    box.className = "cb-clone-replybox";
    box.style.cssText = "margin:8px 0";
    var ta = document.createElement("textarea");
    ta.rows = 3; ta.style.cssText = "width:100%;max-width:520px";
    ta.setAttribute("aria-label", "Reply");
    box.appendChild(ta);
    nav.parentElement.appendChild(box);
    ta.focus();
    return false;
  };

  window.clickEdit = function (id) {
    var row = _up(_evtTarget(null), function (n) {
      return n.parentElement && n.parentElement.querySelector(".comment-nav");
    });
    var body = row && (row.parentElement.querySelector(".comment-body, p") || null);
    if (!body) return false;
    var on = body.getAttribute("contenteditable") === "true";
    body.setAttribute("contenteditable", on ? "false" : "true");
    if (!on) body.focus();
    return false;
  };

  /* 课程笔记。同样没有服务端端点：本次会话内可见，刷新即失。已声明。 */
  window.newAnnotation = function () {
    var pane = document.querySelector(".annotations-pane");
    if (!pane) return false;
    var wrap = document.createElement("div");
    wrap.className = "cb-clone-annotation";
    wrap.style.cssText = "margin:10px 0;padding:10px;border:1px solid #ddd";
    var ta = document.createElement("textarea");
    ta.rows = 3; ta.style.cssText = "width:100%";
    ta.setAttribute("aria-label", "Note");
    ta.placeholder = "Your note";
    wrap.appendChild(ta);
    pane.insertBefore(wrap, pane.firstChild);
    ta.focus();
    return false;
  };

  /* 通知面板 [Clear All]。源站是服务端清除；这里记在 sessionStorage，
     因为源站那个 onclick 后面紧跟 location.reload()，纯 DOM 改动会被冲掉。 */
  window.hideActivity = function (ev, id) {
    if (ev && ev.preventDefault) ev.preventDefault();
    try { sessionStorage.setItem("cb-clone-activity-cleared", "1"); } catch (e) {}
    _applyClearedActivity();
    return false;
  };
  function _applyClearedActivity() {
    var cleared = false;
    try { cleared = sessionStorage.getItem("cb-clone-activity-cleared") === "1"; } catch (e) {}
    if (!cleared) return;
    var host = document.querySelector("#offcanvasRight, .offcanvas");
    if (!host) return;
    var list = host.querySelectorAll(".activity-item, .notification, .activity");
    for (var i = 0; i < list.length; i++) list[i].style.display = "none";
  }

  /* 源站分析埋点：必须存在（否则 onclick 抛错），且必须不发任何请求。 */
  window.ga = function () { return undefined; };
  window.trackLearningJourney = function () { return undefined; };

  /* UsableNet 无障碍挂件是第三方，按 §4.5 已整体移除；
     其触发器 <div id="usntA40Toggle" style="display:none"> 本就不可见。
     这里只保证 onclick 不抛错并阻止 <a href="#"> 跳转。 */
  window.enableUsableNetAssistive = function () { return false; };


  /* ------------------------------------------------------------------
     Bootstrap 3 控件的接住层。

     源站的 tab / collapse / dropdown 全靠 bootstrap.js，它按 §4.5 被整体剔除。
     这些控件不写内联 onclick，所以剔除后**不报错、只是没反应** —— 比
     ReferenceError 那一类更难发现：三套浏览器审计与 118 条测试全绿，
     而 531 个课程页上 Chapters / Materials / Gallery / Discussions /
     Annotations / Transcript 六个页签一个都点不开，内容就在 DOM 里出不来。

     CSS 判据取自出货件自身：
       .collapse.in{display:block}      → 开合切 .in
       .tab-content>.active{display:block} → 切 .active
       .open>.dropdown-menu{display:block} → 切父节点 .open
     ------------------------------------------------------------------ */
  function _byRef(ref) {
    if (!ref) return null;
    ref = String(ref).trim();
    if (ref.charAt(0) === "#") {
      /* id 可能以数字开头（源站有 #1006-1-chapters），querySelector 会抛，
         getElementById 不会 —— jQuery 当年就是这么兜的。 */
      return document.getElementById(ref.slice(1));
    }
    try { return document.querySelector(ref); } catch (e) { return null; }
  }
  function _closestAttr(node, sel) {
    if (!node || !node.closest) return null;
    try { return node.closest(sel); } catch (e) { return null; }
  }

  function wireBootstrap() {
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (!t || t.nodeType !== 1) return;

      var tab = _closestAttr(t, '[data-toggle="tab"], [data-toggle="pill"]');
      if (tab) {
        var pane = _byRef(tab.getAttribute("href") || tab.getAttribute("data-target"));
        if (pane && pane.parentElement) {
          e.preventDefault();
          var sibs = pane.parentElement.children;
          for (var i = 0; i < sibs.length; i++) {
            sibs[i].classList.remove("active", "in");
          }
          pane.classList.add("active", "in");
          var li = tab.parentElement;
          if (li && li.parentElement) {
            var ls = li.parentElement.children;
            for (var j = 0; j < ls.length; j++) ls[j].classList.remove("active");
            li.classList.add("active");
          }
          tab.setAttribute("aria-selected", "true");
        }
        return;
      }

      var col = _closestAttr(t, '[data-toggle="collapse"]');
      if (col) {
        var box = _byRef(col.getAttribute("data-target") || col.getAttribute("href"));
        if (box) {
          e.preventDefault();
          var open = box.classList.contains("in");
          if (open) { box.classList.remove("in"); } else { box.classList.add("in"); }
          if (open) { col.classList.add("collapsed"); } else { col.classList.remove("collapsed"); }
          col.setAttribute("aria-expanded", String(!open));
        }
        return;
      }

      var dd = _closestAttr(t, '[data-toggle="dropdown"]');
      if (dd && dd.parentElement) {
        e.preventDefault();
        var wasOpen = dd.parentElement.classList.contains("open");
        _closeDropdowns();
        if (!wasOpen) dd.parentElement.classList.add("open");
        return;
      }

      /* 点在别处：关掉打开的下拉（菜单内部的点击不算） */
      if (!_closestAttr(t, ".dropdown-menu")) _closeDropdowns();
    });

    /* popover 是纯展示的悬浮说明，源站文案在 data-content 里。
       不引第三方库，退回浏览器原生 title，信息不丢。 */
    var pops = document.querySelectorAll('[data-toggle="popover"][data-content]');
    for (var k = 0; k < pops.length; k++) {
      if (!pops[k].getAttribute("title")) {
        pops[k].setAttribute("title", pops[k].getAttribute("data-content") || "");
      }
    }
  }
  function _closeDropdowns() {
    var open = document.querySelectorAll(".open > .dropdown-menu");
    for (var i = 0; i < open.length; i++) open[i].parentElement.classList.remove("open");
  }

  function boot() {
    wireCommonInteractions();
    wireModals();
    wireForms();
    wireStateButtons();
    hydrateMyClasses();
    hydrateSearch();
    hydrateChallengeStep();
    hydrateNav();
    hydrateRecommended();
    realignSubstitutedCards();
    wireTestimonialCarousel();
    hydrateLazyImages();
    wirePlayerPlaceholders();
    _applyClearedActivity();
    wireBootstrap();
    document.documentElement.setAttribute("data-cb-clone", "ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
