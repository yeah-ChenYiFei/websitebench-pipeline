// Asana offline clone — authenticated app SPA.
// History-based routing under /app/*; all data via the local /api.
(function () {
  "use strict";

  var ME = null; // {user, workspace, workspaces, role}
  var PROJECTS = [];
  var UNREAD = 0;
  var SELECTED = {}; // task_id -> true (bulk selection)
  var FILTERS = {};  // current list filters
  var SIDEBAR_COLLAPSED = false;
  var SIDEBAR_OPEN = false;
  var root = document.getElementById("app");

  // ---------------- helpers ----------------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(html) {
    var t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  async function api(path, opts) {
    opts = opts || {};
    var init = { credentials: "same-origin", method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined && !(opts.body instanceof FormData)) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    } else if (opts.body instanceof FormData) {
      init.body = opts.body;
    }
    var res = await fetch("/api" + path, init);
    if (res.status === 401) { location.assign("/-/login"); throw new Error("unauthorized"); }
    var data = null;
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok) {
      var msg = (data && data.error && data.error.message) ||
        (data && data.message) || "Something went wrong.";
      var err = new Error(msg); err.status = res.status; err.code = data && data.error && data.error.code;
      throw err;
    }
    return data;
  }
  function toast(msg, isError) {
    var box = document.querySelector(".toasts") || document.body.appendChild(el('<div class="toasts"></div>'));
    var t = el('<div class="toast' + (isError ? " error" : "") + '">' + esc(msg) + "</div>");
    box.appendChild(t);
    setTimeout(function () { t.remove(); }, 3400);
  }
  function avatar(name, color, initials, small) {
    return '<span class="avatar' + (small ? " sm" : "") + '" style="background:' +
      esc(color || "#6d6e6f") + '" title="' + esc(name || "") + '">' + esc(initials || "?") + "</span>";
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function dueClass(iso, completed) {
    if (!iso || completed) return "";
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var d = new Date(iso + "T00:00:00");
    if (d < today) return " overdue";
    if (d.getTime() === today.getTime()) return " today";
    return "";
  }
  function ago(ts) {
    var s = Math.max(1, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }
  function greeting() {
    var h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  }

  // ---------------- routing ----------------
  function nav(path) { history.pushState({}, "", path); route(); }
  window.addEventListener("popstate", route);
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest("a[data-nav]");
    if (a) { ev.preventDefault(); nav(a.getAttribute("href")); }
  });

  function route() {
    closePane();
    var p = location.pathname.replace(/\/+$/, "") || "/app/home";
    var m;
    var activeMode = document.querySelector(".mode-button.active");
    if (activeMode && activeMode.dataset.mode !== currentMode()) shell("");
    if (p === "/app" || p === "/app/home") return viewHome();
    if ((m = p.match(/^\/app\/agents(?:\/(\w+))?$/))) return viewAgents(m[1] || "overview");
    if ((m = p.match(/^\/app\/strategy(?:\/(\w+))?$/))) return viewStrategy(m[1] || "overview");
    if ((m = p.match(/^\/app\/knowledge(?:\/(\w+))?$/))) return viewKnowledge(m[1] || "overview");
    if ((m = p.match(/^\/app\/people(?:\/(\w+))?$/))) return viewPeople(m[1] || "directory");
    if (p === "/app/more") return viewMore();
    if (p === "/app/tasks") return viewMyTasks();
    if (p === "/app/tasks/upcoming") return viewMyTasks("upcoming");
    if (p === "/app/tasks/overdue") return viewMyTasks("overdue");
    if (p === "/app/projects") return viewProjects();
    if ((m = p.match(/^\/app\/project\/([^/]+)(?:\/(\w+))?$/))) return viewProject(m[1], m[2] || null);
    if (p === "/app/search") return viewSearch(new URLSearchParams(location.search).get("q") || "");
    if (p === "/app/inbox") return viewInbox();
    if (p === "/app/portfolios") return viewPortfolios();
    if ((m = p.match(/^\/app\/portfolio\/([^/]+)$/))) return viewPortfolio(m[1]);
    if (p === "/app/goals") return viewGoals();
    if (p === "/app/activity") return viewActivity();
    if (p === "/app/settings") return viewSettings(new URLSearchParams(location.search).get("tab") || "profile");
    if (p === "/app/admin") return viewAdmin();
    if (p === "/app/invite") return viewInvite();
    if (p === "/app/billing") return viewBilling();
    if (p === "/app/trash") return viewTrash();
    if (p === "/app/help") return viewHelp();
    return viewNotFound(p);
  }

  // ---------------- shell ----------------
  var APP_ICON_PATHS = {
    work: "M24.5068 -.0001C28.649-.0001 32.0068 3.3578 32.0068 7.4999c0 3.0004-1.7622 5.5866-4.308 6.7851-.6802.3202-1.192.9621-1.192 1.7139s.512 1.3937 1.192 1.714c2.546 1.1987 4.308 3.7865 4.308 6.7871 0 4.142-3.3578 7.5-7.5 7.5-3.0064-.0002-5.5986-1.7696-6.7942-4.3238-.3145-.6716-.9479-1.1762-1.6896-1.1762-.7476 0-1.3846.5126-1.6961 1.1922-1.184 2.5836-3.7919 4.378-6.8201 4.378-4.1419-.0002-7.5-3.358-7.5-7.5.0003-2.9876 1.7479-5.5663 4.2763-6.7718.6974-.3325 1.2237-.9918 1.2237-1.7644s-.5263-1.4318-1.2236-1.7642C1.7548 13.0646.0068 10.4875.0068 7.4999.0068 3.3579 3.365.0002 7.5068-.0001c3.0008 0 5.5887 1.7628 6.7874 4.309.32.6796.9614 1.191 1.7126 1.191s1.3927-.5114 1.7127-1.191C18.9182 1.7627 21.5062.0001 24.5068-.0001ZM16.0068 9.4999c-.7512 0-1.3926.5113-1.7127 1.1909-.7376 1.5662-2.0012 2.8346-3.5636 3.5792-.6974.3323-1.2237.9915-1.2237 1.764s.5264 1.4318 1.2238 1.7643c1.5395.7339 2.7889 1.9772 3.531 3.5123.3284.6794.9742 1.1894 1.7289 1.1894.7608 0 1.4103-.5182 1.736-1.2058.7436-1.5704 2.0164-2.8406 3.5885-3.5812.6802-.3204 1.1918-.9623 1.1918-1.7141s-.5116-1.3938-1.1918-1.714c-1.5768-.7426-2.8528-2.0175-3.5954-3.5941-.3202-.6795-.9616-1.1909-1.7128-1.1909Z",
    agents: "M13.0073 4.0898C13.0022.4564 17.1674-1.3675 19.604 1.2011l11.2715 11.8867c.7245.7641 1.1316 1.8012 1.1318 2.8818v.0997c-.0001 1.0806-.4073 2.1176-1.1318 2.8818L19.6421 30.7978c-2.4323 2.5651-6.5919.7526-6.5977-2.875l-.0117-7.6826c-.001-.6849-.5564-1.2401-1.2412-1.2403-.3384 0-.6623.1386-.8965.3828l-4.2314 4.416C4.2098 26.3593.0194 24.5544.0161 20.9355L.0073 11.0839c-.0028-3.6254 4.198-5.449 6.6524-2.8877l4.2392 4.4248c.2322.2422.5532.3789.8887.3789.6807 0 1.2323-.5518 1.2314-1.2324l-.0117-7.6777Z",
    strategy: "M19.535 3.417C18.752 2.217 17.431 1.5 16 1.5c-1.431 0-2.752.716-3.534 1.916L.696 21.443c-.866 1.326-.933 2.949-.179 4.342C1.268 27.172 2.656 28 4.23 28h23.539c1.574 0 2.962-.828 3.713-2.215.754-1.393.688-3.016-.179-4.342L19.535 3.417Z",
    knowledge: "M19.0054.0012c.5516-.0276 1.0019.4242 1.0019.9777v9.9233c0 .6222.562 1.0948 1.1592.9248 3.4919-.9944 6.0419-3.4111 9.8418-3.7844.5495-.0538.999.3998.999.9532v18.0381c-.0001.5534-.4497.9963-.999 1.053-4.1964.4333-6.7155 3.4839-11.002 3.9087-.5495.0544-.9989-.3998-.999-.9532v-6.0245c0-.5751-.4845-1.0354-1.0547-.9698-6.3185.7273-10.2016 4.6063-16.9433 4.9636-.5515.0292-1.0019-.4223-1.002-.9757V6.0286c0-.5295.4132-.9651.9385-1.0217C7.8044 4.2694 12.0132.3505 19.0054.0012Z",
    people: "M16.0073 0c4.9706 0 9 4.0294 9 9 0 3.3202-1.799 6.2184-4.4744 7.7781-.3161.1842-.5256.5148-.5256.8806 0 .4521.3154.8408.7522.9573 5.886 1.5708 10.3368 5.9833 11.2252 11.3913.1791 1.0905-.7336 1.9927-1.8388 1.9927H1.8687c-1.1052 0-2.018-.9022-1.8388-1.9927.8884-5.4079 5.3393-9.8205 11.2252-11.3912.4368-.1166.7522-.5053.7522-.9574 0-.3658-.2095-.6964-.5256-.8806C8.8062 15.2184 7.0073 12.3202 7.0073 9c0-4.9706 4.0294-9 9-9Z",
    more: "M16 13c1.7 0 3 1.3 3 3s-1.3 3-3 3-3-1.3-3-3 1.3-3 3-3ZM3 13c1.7 0 3 1.3 3 3s-1.3 3-3 3-3-1.3-3-3 1.3-3 3-3Zm26 0c1.7 0 3 1.3 3 3s-1.3 3-3 3-3-1.3-3-3 1.3-3 3-3Z",
    home: "M31.6 12.2 17.8 2.6c-1.1-.8-2.6-.8-3.7 0L.4 12.2c-.5.3-.6.9-.3 1.4s.9.6 1.4.3L4 12.1v10.8c0 3.9 3.2 7.1 7.1 7.1H21c3.9 0 7.1-3.2 7.1-7.1V12.1l2.4 1.7c.1.2.3.2.5.2.3 0 .6-.2.8-.4.3-.5.2-1.1-.2-1.4ZM26 22.9c0 2.8-2.3 5-5 5h-9.9c-2.8 0-5-2.3-5-5V10.7l9.4-6.5c.4-.3.9-.3 1.3 0l9.3 6.5-.1 12.2Z",
    tasks: "M29.1 20.9M16 32C7.2 32 0 24.8 0 16S7.2 0 16 0s16 7.2 16 16-7.2 16-16 16Zm0-30C8.3 2 2 8.3 2 16s6.3 14 14 14 14-6.3 14-14S23.7 2 16 2Zm-3.1 20.6c-.3 0-.5-.1-.7-.3l-3.9-3.9c-.3-.4-.3-1 0-1.4s1-.4 1.4 0l3.1 3.1 8.6-8.6c.4-.4 1-.4 1.4 0s.4 1 0 1.4l-9.4 9.4c0 .2-.2.4-.5.4Z",
    inbox: "M26 12c3.3137 0 6-2.6863 6-6s-2.6863-6-6-6-6 2.6863-6 6 2.6863 6 6 6Zm3.97 8.635C28.718 19.523 28 17.924 28 16.249V15c0-.552-.448-1-1-1s-1 .448-1 1v1.249c0 2.246.962 4.389 2.641 5.881.367.326.462.849.239 1.303-.167.339-.582.567-1.03.567H4.151c-.449 0-.863-.228-1.03-.568-.224-.453-.128-.977.239-1.302C5.038 20.638 6.001 18.495 6.001 16.249V12c0-2.706 1.063-5.24 2.994-7.136 1.931-1.896 4.489-2.921 7.194-2.862.701.012 1.4.102 2.077.266.536.128 1.077-.2 1.207-.737.129-.537-.2-1.077-.737-1.207A12.1 12.1 0 0 0 16.225.003C12.961-.049 9.91 1.164 7.594 3.438 5.277 5.713 4.001 8.754 4.001 12.001v4.249c0 1.675-.718 3.273-1.97 4.386-1.047.932-1.33 2.411-.704 3.682.504 1.023 1.613 1.684 2.824 1.684h23.698c1.211 0 2.32-.661 2.824-1.683.626-1.271.344-2.75-.704-3.682ZM19.733 28H20.896C19.963 29.817 18.081 31 16 31s-3.963-1.183-4.896-3h8.629Z",
    projects: "M10 13.5c.8 0 1.5.7 1.5 1.5s-.7 1.5-1.5 1.5-1.5-.7-1.5-1.5.7-1.5 1.5-1.5ZM23 14h-8c-.6 0-1 .4-1 1s.4 1 1 1h8c.6 0 1-.4 1-1s-.4-1-1-1Zm0 6h-8c-.6 0-1 .4-1 1s.4 1 1 1h8c.6 0 1-.4 1-1s-.4-1-1-1Zm-13-.5c.8 0 1.5.7 1.5 1.5s-.7 1.5-1.5 1.5-1.5-.7-1.5-1.5.7-1.5 1.5-1.5ZM24 2h-2.2C21.4.8 20.3 0 19 0h-6c-1.3 0-2.4.8-2.8 2H8C4.7 2 2 4.7 2 8v18c0 3.3 2.7 6 6 6h16c3.3 0 6-2.7 6-6V8c0-3.3-2.7-6-6-6ZM13 2h6c.6 0 1 .4 1 1v2c0 .6-.4 1-1 1h-6c-.6 0-1-.4-1-1V3c0-.6.4-1 1-1Zm15 24c0 2.2-1.8 4-4 4H8c-2.2 0-4-1.8-4-4V8c0-2.2 1.8-4 4-4h2v1c0 1.7 1.3 3 3 3h6c1.7 0 3-1.3 3-3V4h2v22Z",
    portfolios: "M29 8c1.6569 0 3 1.3431 3 3v14c0 2.7614-2.2386 5-5 5H5c-2.7614 0-5-2.2386-5-5V5c0-1.6569 1.3431-3 3-3h9.2c.3693 0 .7086.2036.8824.5294l2.0705 3.8824C15.6743 7.3894 16.6921 8 17.8 8H29Zm1 3v14c0 1.6569-1.3431 3-3 3H5c-1.6569 0-3-1.3431-3-3V10h27c.5523 0 1 .4477 1 1ZM13.7999 8c-.1522-.203-.29-.419-.4117-.6471L11.6 4H3c-.5523 0-1 .4477-1 1v3h11.7999Z"
  };
  function appIcon(name, small) {
    return '<svg class="app-icon' + (small ? ' app-icon-small' : '') + '" viewBox="0 0 32 32" aria-hidden="true"><path d="' + APP_ICON_PATHS[name] + '"></path></svg>';
  }
  function projectMark() {
    return '<span class="proj-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M24 3v6h-6V3h6ZM0 9h6V3H0v6Zm0 12h6V11H0v10Zm9-4h6V3H9v14Z"></path></svg></span>';
  }
  function currentMode() {
    var path = location.pathname;
    if (path.indexOf("/app/agents") === 0) return "agents";
    if (path.indexOf("/app/strategy") === 0 || path === "/app/goals" || path.indexOf("/app/portfolio") === 0) return "strategy";
    if (path.indexOf("/app/knowledge") === 0) return "knowledge";
    if (path.indexOf("/app/people") === 0 || path === "/app/invite") return "people";
    if (path === "/app/more" || /^\/app\/(settings|admin|billing|trash)/.test(path)) return "more";
    return "work";
  }
  function modeSidebar(mode, projItems) {
    if (mode === "work") {
      return '<div class="workspace-primary">' + sideItem("/app/home", appIcon("home"), "Home") +
        sideItem("/app/inbox", appIcon("inbox"), "Inbox", UNREAD) +
        '</div><div class="workspace-separator"></div><div class="workspace-links">' +
        sideItem("/app/tasks", appIcon("tasks"), "My tasks") +
        sideItem("/app/projects", appIcon("projects"), "Projects") +
        sideItem("/app/portfolios", appIcon("portfolios"), "Portfolios") +
        '</div><div class="side-section"><div class="side-head"><span><span class="side-disclosure"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M12.617 6.576A1 1 0 0 0 12 7.5v17a1 1 0 0 0 1.707.707l8.5-8.5a.999.999 0 0 0 0-1.414l-8.5-8.5a.998.998 0 0 0-1.09-.217Z"></path></svg></span> Work</span>' +
        '<button id="side-add-project" title="Create project" aria-label="Create project"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 10V4c0-1.1.9-2 2-2s2 .9 2 2v6h6c1.1 0 2 .9 2 2s-.9 2-2 2h-6v6c0 1.1-.9 2-2 2s-2-.9-2-2v-6H4c-1.1 0-2-.9-2-2s.9-2 2-2h6Z"></path></svg></button></div>' + projItems + '</div>';
    }
    var links = {
      agents: [["/app/agents", "agents", "Overview"], ["/app/agents/library", "projects", "Agent library"], ["/app/agents/activity", "strategy", "Agent activity"]],
      strategy: [["/app/strategy", "strategy", "Overview"], ["/app/goals", "strategy", "Goals"], ["/app/portfolios", "portfolios", "Portfolios"], ["/app/strategy/reporting", "strategy", "Reporting"]],
      knowledge: [["/app/knowledge", "knowledge", "Overview"], ["/app/knowledge/collections", "projects", "Collections"], ["/app/knowledge/templates", "portfolios", "Templates"]],
      people: [["/app/people", "people", "Directory"], ["/app/people/teams", "projects", "Teams"], ["/app/invite", "people", "Invite people"]],
      more: [["/app/more", "more", "Overview"], ["/app/settings", "people", "My settings"], ["/app/admin", "projects", "Workspace settings"], ["/app/billing", "portfolios", "Billing"], ["/app/trash", "inbox", "Trash"]],
    }[mode];
    return '<div class="workspace-primary mode-links">' + links.map(function (item) {
      return sideItem(item[0], appIcon(item[1]), item[2]);
    }).join("") + '</div><div class="workspace-separator"></div><div class="mode-note">' +
      ({ agents: "Build and monitor AI teammates.", strategy: "Connect goals to execution.", knowledge: "Find shared team knowledge.", people: "Manage people and teams.", more: "Workspace tools and settings." }[mode]) + '</div>';
  }
  function shell(contentHtml) {
    var projItems = PROJECTS.slice(0, 1).map(function (p) {
      return '<a class="side-item" data-nav href="/app/project/' + esc(p.project_id) + '">' +
        projectMark() +
        '<span class="tname">Team schedule</span></a>';
    }).join("");
    var wsOptions = (ME.workspaces || []).map(function (w, index) {
      return '<option value="' + esc(w.workspace_id) + '"' +
        (w.workspace_id === ME.workspace.workspace_id ? " selected" : "") + ">" +
        (index ? "Demo Workspace " + (index + 1) : "Demo Workspace") + "</option>";
    }).join("");
    var mode = currentMode();
    var modeTitle = { work: "Work", agents: "Agents", strategy: "Strategy", knowledge: "Knowledge", people: "People", more: "More" }[mode];
    var modeButtons = [["work", "/app/home", "Work"], ["agents", "/app/agents", "Agents"],
      ["strategy", "/app/strategy", "Strategy"], ["knowledge", "/app/knowledge", "Knowledge"],
      ["people", "/app/people", "People"], ["more", "/app/more", "More"]].map(function (item) {
        return '<a class="mode-button' + (mode === item[0] ? ' active' : '') + '" data-mode="' + item[0] +
          '" data-nav href="' + item[1] + '" aria-label="' + item[2] + '"><span aria-hidden="true">' +
          appIcon(item[0]) + '</span><small>' + item[2] + '</small></a>';
      }).join("");
    root.innerHTML =
      '<header class="topbar">' +
      '<div class="hamb-slot"><button class="hamb" id="hamb" aria-label="Toggle menu rail" aria-expanded="false"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M0 4.5A1.5 1.5 0 0 1 1.5 3h29a1.5 1.5 0 1 1 0 3h-29A1.5 1.5 0 0 1 0 4.5ZM30.5 15h-29a1.5 1.5 0 1 0 0 3h29a1.5 1.5 0 1 0 0-3Zm0 12h-29a1.5 1.5 0 1 0 0 3h29a1.5 1.5 0 1 0 0-3Z"></path></svg></button></div>' +
      '<button class="create-btn" id="create-btn" aria-label="Create"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M26,14h-8V6c0-1.1-0.9-2-2-2l0,0c-1.1,0-2,0.9-2,2v8H6c-1.1,0-2,0.9-2,2l0,0c0,1.1,0.9,2,2,2h8v8c0,1.1,0.9,2,2,2l0,0c1.1,0,2-0.9,2-2v-8h8c1.1,0,2-0.9,2-2v0C28,14.9,27.1,14,26,14z"></path></svg><span class="create-label">Create</span></button>' +
      '<div class="searchbox"><span class="icon" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M13.999 28c3.5 0 6.697-1.3 9.154-3.432l6.139 6.139a.997.997 0 0 0 1.414 0 .999.999 0 0 0 0-1.414l-6.139-6.139A13.93 13.93 0 0 0 27.999 14c0-7.72-6.28-14-14-14s-14 6.28-14 14 6.28 14 14 14Zm0-26c6.617 0 12 5.383 12 12s-5.383 12-12 12-12-5.383-12-12 5.383-12 12-12Z"></path></svg></span>' +
      '<input id="global-search" placeholder="Search" aria-label="Search"></div>' +
      '<button class="assistant-btn" id="assistant-btn" aria-label="Open local assistant"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M24.75 0h-1.5A5.25 5.25 0 0 1 18 5.25v1.5A5.25 5.25 0 0 1 23.25 12h1.5A5.25 5.25 0 0 1 30 6.75v-1.5A5.25 5.25 0 0 1 24.75 0ZM0 15c4.444 0 7 2.5 7 7h2c0-4.5 2.5-7 7-7v-2c-4.5 0-7-2.5-7-7H7c0 4.5-2.5 7-7 7v2Zm20.75 17A5.25 5.25 0 0 1 26 26.75v-1.5A5.25 5.25 0 0 1 20.75 20h-1.5A5.25 5.25 0 0 1 14 25.25v1.5A5.25 5.25 0 0 1 19.25 32h1.5Z"></path></svg></button>' +
      "</header>" +
      '<div class="app-frame">' +
      '<nav class="sidebar' + (SIDEBAR_COLLAPSED ? " collapsed" : "") +
      (SIDEBAR_OPEN ? " open" : "") + '" id="sidebar" aria-label="Main navigation">' +
      '<div class="mode-rail" aria-label="Workspace modes">' +
      modeButtons +
      '<span class="mode-spacer"></span>' +
      '<button class="mode-help" id="help-menu" type="button" aria-label="Help"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M15.999 0c-8.822 0-16 7.178-16 16s7.178 16 16 16 16-7.178 16-16-7.178-16-16-16Zm0 30c-7.72 0-14-6.28-14-14s6.28-14 14-14 14 6.28 14 14-6.28 14-14 14Zm2-6a2 2 0 1 1-4.001-.001A2 2 0 0 1 18 24Zm4-12.264c0 2.076-1.136 3.928-3.039 4.952-1.185.637-1.461.87-1.461 1.705V20h-3v-1.606c0-2.712 1.828-3.695 3.037-4.347.441-.237 1.463-.936 1.463-2.31 0-.643-.217-2.737-3-2.737-2.491 0-3 1.68-3 2.13v1.212h-3V11.13c0-2.131 1.861-5.131 6-5.131s6 2.975 6 5.737Z"></path></svg></button>' +
      '<button class="avatar mode-profile" id="me-menu" style="background:#a88ff0" aria-label="Open Synthetic User menu">QA</button>' +
      '</div>' +
      '<div class="workspace-rail">' +
      '<button class="workspace-title" id="workspace-title" aria-label="Switch Demo Workspace">' +
      '<span>' + modeTitle + '</span><span class="workspace-chevron">⌄</span></button>' +
      modeSidebar(mode, projItems) +
      '<div class="side-foot"><div class="trial-card"><span class="trial-ring" aria-hidden="true"></span>' +
      '<span><strong>Advanced free trial</strong><small>14 days left</small></span>' +
      '<button type="button" id="trial-info">Add billing info</button></div>' +
      '<a class="side-item invite-row" data-nav href="/app/invite"><span><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M31 26h-3v-3c0-.6-.4-1-1-1s-1 .4-1 1v3h-3c-.6 0-1 .4-1 1s.4 1 1 1h3v3c0 .6.4 1 1 1s1-.4 1-1v-3h3c.6 0 1-.4 1-1s-.4-1-1-1ZM16 18c4.4 0 8-3.6 8-8s-3.6-8-8-8-8 3.6-8 8 3.6 8 8 8Zm0-14c3.3 0 6 2.7 6 6s-2.7 6-6 6-6-2.7-6-6 2.7-6 6-6Zm5.2 16H8.8C5 20 2 23 2 26.8V31c0 .6.4 1 1 1s1-.4 1-1v-4.2C4 24.2 6.2 22 8.8 22h12.4c.6 0 1-.4 1-1s-.4-1-1-1Z"></path></svg></span>Invite</a>' +
      '<select id="ws-switch" class="workspace-switch-native" aria-label="Switch workspace">' + wsOptions + '</select></div>' +
      '</div></nav>' +
      '<main class="main"><div class="content"><div class="page" id="page">' + contentHtml +
      "</div></div></main></div>";

    document.getElementById("hamb").onclick = function () {
      var sb = document.getElementById("sidebar");
      if (window.innerWidth <= 860) {
        SIDEBAR_OPEN = !SIDEBAR_OPEN;
        sb.classList.toggle("open", SIDEBAR_OPEN);
      } else {
        SIDEBAR_COLLAPSED = !SIDEBAR_COLLAPSED;
        sb.classList.toggle("collapsed", SIDEBAR_COLLAPSED);
      }
      this.setAttribute("aria-expanded", String(window.innerWidth <= 860 ? SIDEBAR_OPEN : !SIDEBAR_COLLAPSED));
    };
    document.getElementById("create-btn").onclick = openCreateMenu;
    document.getElementById("assistant-btn").onclick = openAssistant;
    var sideAdd = document.getElementById("side-add-project");
    if (sideAdd) sideAdd.onclick = function () { openProjectModal(); };
    document.getElementById("workspace-title").onclick = openWorkspaceSwitcher;
    document.getElementById("ws-switch").onchange = async function () {
      await api("/workspace/switch", { method: "POST", body: { workspace_id: this.value } });
      await loadMe(); nav("/app/home");
    };
    var gs = document.getElementById("global-search");
    gs.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && gs.value.trim()) nav("/app/search?q=" + encodeURIComponent(gs.value.trim()));
    });
    document.getElementById("me-menu").onclick = openMeMenu;
    document.getElementById("help-menu").onclick = openHelpMenu;
    document.getElementById("trial-info").onclick = function () { nav("/app/billing"); };
    highlightSide();
  }
  function sideItem(href, icon, label, badge) {
    return '<a class="side-item" data-nav href="' + href + '"><span>' + icon + "</span>" +
      esc(label) + (badge ? '<span class="badge">' + badge + "</span>" : "") + "</a>";
  }
  function highlightSide() {
    document.querySelectorAll(".side-item").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("href") === location.pathname);
    });
  }
  function setPage(html) {
    if (!document.getElementById("page")) shell("");
    var page = document.getElementById("page");
    page.className = "page" + (arguments[1] ? " " + arguments[1] : "");
    page.innerHTML = html;
    highlightSide();
  }
  function loadingPage() { setPage('<div class="loading"><span class="spinner"></span><p>Loading…</p></div>'); }

  function openMeMenu() {
    openModal('<div class="profile-menu-head">' + avatar(ME.user.display_name, ME.user.avatar_color, ME.user.initials) +
      '<div><h2>' + esc(ME.user.display_name) + '</h2><p class="page-sub">' + esc(ME.user.email) + '</p></div></div>' +
      '<div class="profile-menu-actions">' +
      '<button class="tbtn" data-go="/app/settings">Profile &amp; settings</button>' +
      '<button class="tbtn" id="profile-workspace">Switch workspace</button>' +
      '<button class="tbtn" data-go="/app/people">People directory</button>' +
      '<button class="tbtn" id="profile-help">Help &amp; getting started</button>' +
      '<button class="tbtn danger" id="logout-btn">Log out</button></div>');
    document.querySelectorAll("[data-go]").forEach(function (b) {
      b.onclick = function () { closeModal(); nav(b.dataset.go); };
    });
    document.getElementById("logout-btn").onclick = async function () {
      await api("/auth/logout", { method: "POST" });
      location.assign("/-/login");
    };
    document.getElementById("profile-workspace").onclick = function () { closeModal(); openWorkspaceSwitcher(); };
    document.getElementById("profile-help").onclick = function () { closeModal(); openHelpMenu(); };
  }

  function openHelpMenu() {
    openModal('<h2>How can we help?</h2><p class="page-sub">Get help without leaving your current work.</p>' +
      '<div class="help-menu-grid"><button class="tbtn" data-help-go="/app/help">Help center</button>' +
      '<button class="tbtn" data-help-go="/app/knowledge">Browse team knowledge</button>' +
      '<button class="tbtn" id="help-shortcuts">Keyboard shortcuts</button>' +
      '<button class="tbtn" id="help-support">Contact support</button></div>' +
      '<p id="help-result" class="assistant-answer" aria-live="polite"></p>');
    document.querySelectorAll("[data-help-go]").forEach(function (button) {
      button.onclick = function () { closeModal(); nav(button.dataset.helpGo); };
    });
    document.getElementById("help-shortcuts").onclick = function () {
      document.getElementById("help-result").textContent = "Press / to search, Tab to move, and Esc to close a dialog.";
    };
    document.getElementById("help-support").onclick = function () {
      document.getElementById("help-result").textContent = "Support is available inside this local demo; no message was sent.";
    };
  }

  function openAssistant() {
    openModal('<h2>Local assistant</h2>' +
      '<p class="page-sub">Get help with this synthetic Demo Workspace. Nothing is sent outside this device.</p>' +
      '<div class="assistant-prompts">' +
      '<button class="tbtn" data-assistant="tasks">Summarize my tasks</button>' +
      '<button class="tbtn" data-assistant="projects">Show active projects</button>' +
      '<button class="tbtn" data-assistant="help">Open help</button></div>' +
      '<p id="assistant-answer" class="assistant-answer" aria-live="polite"></p>');
    document.querySelectorAll("[data-assistant]").forEach(function (button) {
      button.onclick = function () {
        if (button.dataset.assistant === "help") { closeModal(); nav("/app/help"); return; }
        document.getElementById("assistant-answer").textContent = button.dataset.assistant === "tasks" ?
          "Your local task list is ready on Home and My tasks." :
          PROJECTS.length + " active local projects are available in Demo Workspace.";
      };
    });
  }

  function openWorkspaceSwitcher() {
    openModal('<h2>Demo Workspace</h2><p class="page-sub">Switch between local synthetic workspaces.</p>' +
      '<div class="field"><label for="modal-ws-switch">Workspace</label>' +
      '<select id="modal-ws-switch">' + document.getElementById("ws-switch").innerHTML + '</select></div>' +
      '<div class="modal-actions"><button class="tbtn" id="modal-ws-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="modal-ws-open">Open workspace</button></div>');
    document.getElementById("modal-ws-cancel").onclick = closeModal;
    document.getElementById("modal-ws-open").onclick = async function () {
      await api("/workspace/switch", { method: "POST", body: {
        workspace_id: document.getElementById("modal-ws-switch").value,
      } });
      closeModal(); await loadMe(); nav("/app/home");
    };
  }

  function openCreateMenu() {
    openModal('<h2>Create</h2><div class="modal-actions" style="justify-content:flex-start;flex-wrap:wrap">' +
      '<button class="tbtn" id="cm-task">Task</button>' +
      '<button class="tbtn" id="cm-project">Project</button>' +
      '<button class="tbtn" id="cm-portfolio">Portfolio</button>' +
      '<button class="tbtn" id="cm-goal">Goal</button>' +
      '<button class="tbtn" id="cm-workspace">Workspace</button></div>');
    document.getElementById("cm-task").onclick = function () { closeModal(); openTaskModal(); };
    document.getElementById("cm-project").onclick = function () { closeModal(); openProjectModal(); };
    document.getElementById("cm-portfolio").onclick = function () { closeModal(); openPortfolioModal(); };
    document.getElementById("cm-goal").onclick = function () { closeModal(); openGoalModal(); };
    document.getElementById("cm-workspace").onclick = function () { closeModal(); openWorkspaceModal(); };
  }

  // ---------------- modals ----------------
  function openModal(inner) {
    closeModal();
    var b = el('<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true">' + inner + "</div></div>");
    b.addEventListener("mousedown", function (ev) { if (ev.target === b) closeModal(); });
    document.body.appendChild(b);
    document.addEventListener("keydown", escClose);
    var f = b.querySelector("input,select,textarea,button");
    if (f) f.focus();
  }
  function escClose(ev) { if (ev.key === "Escape") { closeModal(); closePane(); } }
  document.addEventListener("keydown", escClose);
  function closeModal() {
    var b = document.querySelector(".modal-backdrop");
    if (b) b.remove();
  }

  var COLORS = ["#4573d2", "#f06a6a", "#5da283", "#f1bd6c", "#796eff", "#aa62e3", "#f9838c", "#6d6e6f"];
  function colorRow(sel) {
    return '<div class="color-row">' + COLORS.map(function (c) {
      return '<button type="button" class="color-swatch' + (c === sel ? " on" : "") +
        '" data-color="' + c + '" style="background:' + c + '" aria-label="' + c + '"></button>';
    }).join("") + "</div>";
  }
  function wireColorRow(box) {
    box.querySelectorAll(".color-swatch").forEach(function (s) {
      s.onclick = function () {
        box.querySelectorAll(".color-swatch").forEach(function (x) { x.classList.remove("on"); });
        s.classList.add("on");
      };
    });
  }
  function pickedColor() {
    var s = document.querySelector(".color-swatch.on");
    return s ? s.dataset.color : COLORS[0];
  }

  async function memberOptions(sel) {
    var data = await api("/members");
    return '<option value="">Unassigned</option>' + data.members.map(function (m) {
      return '<option value="' + esc(m.user_id) + '"' + (m.user_id === sel ? " selected" : "") + ">" +
        esc(m.display_name) + "</option>";
    }).join("");
  }

  async function openTaskModal(presetProject, presetSection) {
    var opts = await memberOptions(ME.user.user_id);
    var projOpts = '<option value="">No project</option>' + PROJECTS.map(function (p) {
      return '<option value="' + esc(p.project_id) + '"' + (p.project_id === presetProject ? " selected" : "") + ">" + esc(p.name) + "</option>";
    }).join("");
    openModal('<h2>New task</h2>' +
      '<div class="field"><label>Task name</label><input id="nt-name" maxlength="400"></div>' +
      '<div class="field"><label>Project</label><select id="nt-project">' + projOpts + "</select></div>" +
      '<div class="field"><label>Assignee</label><select id="nt-assignee">' + opts + "</select></div>" +
      '<div class="field"><label>Due date</label><input id="nt-due" type="date"></div>' +
      '<div class="field"><label>Priority</label><select id="nt-priority"><option value="">None</option><option>Low</option><option>Medium</option><option>High</option></select></div>' +
      '<div class="field"><label>Description</label><textarea id="nt-notes" rows="3"></textarea></div>' +
      '<p class="form-error" id="nt-err" hidden></p>' +
      '<div class="modal-actions"><button class="tbtn" id="nt-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="nt-create">Create task</button></div>');
    document.getElementById("nt-cancel").onclick = closeModal;
    document.getElementById("nt-create").onclick = async function () {
      var name = document.getElementById("nt-name").value.trim();
      var errEl = document.getElementById("nt-err");
      if (!name) { errEl.textContent = "Task name is required."; errEl.hidden = false; return; }
      try {
        await api("/tasks", { method: "POST", body: {
          name: name,
          project_id: document.getElementById("nt-project").value || null,
          section_id: presetSection || null,
          assignee_user_id: document.getElementById("nt-assignee").value || null,
          due_date: document.getElementById("nt-due").value || null,
          priority: document.getElementById("nt-priority").value || null,
          notes: document.getElementById("nt-notes").value,
        } });
        closeModal(); toast("Task created"); route();
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
  }

  async function openProjectModal(portfolioId) {
    var tpls = (await api("/templates")).templates.map(function (t) {
      return '<option value="' + esc(t.id) + '">' + esc(t.name) + "</option>";
    }).join("");
    openModal('<h2>New project</h2>' +
      '<div class="field"><label>Project name</label><input id="np-name" maxlength="200"></div>' +
      '<div class="field"><label>Template</label><select id="np-template">' + tpls + "</select></div>" +
      '<div class="field"><label>Default view</label><select id="np-view"><option value="list">List</option><option value="board">Board</option><option value="calendar">Calendar</option><option value="timeline">Timeline</option></select></div>' +
      '<div class="field"><label>Color</label>' + colorRow(COLORS[0]) + "</div>" +
      '<p class="form-error" id="np-err" hidden></p>' +
      '<div class="modal-actions"><button class="tbtn" id="np-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="np-create">Create project</button></div>');
    wireColorRow(document.querySelector(".modal"));
    document.getElementById("np-cancel").onclick = closeModal;
    document.getElementById("np-create").onclick = async function () {
      var name = document.getElementById("np-name").value.trim();
      var errEl = document.getElementById("np-err");
      if (!name) { errEl.textContent = "Project name is required."; errEl.hidden = false; return; }
      try {
        var r = await api("/projects", { method: "POST", body: {
          name: name, template: document.getElementById("np-template").value,
          view: document.getElementById("np-view").value, color: pickedColor(),
          portfolio_id: portfolioId || null,
        } });
        closeModal(); await loadProjects(); toast("Project created");
        nav("/app/project/" + r.project_id);
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
  }

  function openPortfolioModal() {
    openModal('<h2>New portfolio</h2>' +
      '<div class="field"><label>Portfolio name</label><input id="npf-name" maxlength="200"></div>' +
      '<div class="field"><label>Color</label>' + colorRow("#796eff") + "</div>" +
      '<p class="form-error" id="npf-err" hidden></p>' +
      '<div class="modal-actions"><button class="tbtn" id="npf-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="npf-create">Create portfolio</button></div>');
    wireColorRow(document.querySelector(".modal"));
    document.getElementById("npf-cancel").onclick = closeModal;
    document.getElementById("npf-create").onclick = async function () {
      var name = document.getElementById("npf-name").value.trim();
      var errEl = document.getElementById("npf-err");
      if (!name) { errEl.textContent = "Portfolio name is required."; errEl.hidden = false; return; }
      try {
        await api("/portfolios", { method: "POST", body: { name: name, color: pickedColor() } });
        closeModal(); toast("Portfolio created"); nav("/app/portfolios");
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
  }

  function openGoalModal() {
    openModal('<h2>New goal</h2>' +
      '<div class="field"><label>Goal name</label><input id="ng-name" maxlength="300"></div>' +
      '<div class="field"><label>Time period</label><select id="ng-period"><option>FY26</option><option>Q3 FY26</option><option>Q4 FY26</option></select></div>' +
      '<p class="form-error" id="ng-err" hidden></p>' +
      '<div class="modal-actions"><button class="tbtn" id="ng-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="ng-create">Create goal</button></div>');
    document.getElementById("ng-cancel").onclick = closeModal;
    document.getElementById("ng-create").onclick = async function () {
      var name = document.getElementById("ng-name").value.trim();
      var errEl = document.getElementById("ng-err");
      if (!name) { errEl.textContent = "Goal name is required."; errEl.hidden = false; return; }
      try {
        await api("/goals", { method: "POST", body: { name: name, time_period: document.getElementById("ng-period").value } });
        closeModal(); toast("Goal created"); nav("/app/goals");
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
  }

  function openWorkspaceModal() {
    openModal('<h2>New workspace</h2>' +
      '<div class="field"><label>Workspace name</label><input id="nw-name" maxlength="120"></div>' +
      '<p class="form-error" id="nw-err" hidden></p>' +
      '<div class="modal-actions"><button class="tbtn" id="nw-cancel">Cancel</button>' +
      '<button class="tbtn primary" id="nw-create">Create workspace</button></div>');
    document.getElementById("nw-cancel").onclick = closeModal;
    document.getElementById("nw-create").onclick = async function () {
      var name = document.getElementById("nw-name").value.trim();
      var errEl = document.getElementById("nw-err");
      if (!name) { errEl.textContent = "Workspace name is required."; errEl.hidden = false; return; }
      try {
        await api("/workspaces", { method: "POST", body: { name: name } });
        closeModal(); await loadMe(); toast("Workspace created — you are now in it");
        nav("/app/home");
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
  }

  // ---------------- task pane ----------------
  function closePane() {
    var p = document.querySelector(".task-pane"); if (p) p.remove();
    var b = document.querySelector(".pane-backdrop"); if (b) b.remove();
  }

  async function openTask(taskId) {
    closePane();
    document.body.appendChild(el('<div class="pane-backdrop"></div>'));
    document.querySelector(".pane-backdrop").onclick = closePane;
    var pane = el('<aside class="task-pane" role="dialog" aria-label="Task details"><div class="loading"><span class="spinner"></span></div></aside>');
    document.body.appendChild(pane);
    var data;
    try { data = await api("/tasks/" + taskId); }
    catch (e) { pane.innerHTML = '<div class="empty"><h3>Task not found</h3></div>'; return; }
    renderTaskPane(pane, data);
  }

  async function renderTaskPane(pane, data) {
    var t = data.task;
    var mopts = await memberOptions(t.assignee_user_id);
    var comments = data.comments.map(function (cm) {
      var mine = cm.author_user_id === ME.user.user_id;
      return '<div class="comment">' + avatar(cm.display_name, cm.avatar_color, cm.initials, true) +
        '<div class="cbody"><div class="cwho">' + esc(cm.display_name) +
        '<span class="cwhen">' + ago(cm.created_at) + (cm.edited_at ? " · edited" : "") + "</span></div>" +
        '<div>' + esc(cm.body) + "</div>" +
        (mine ? '<div style="margin-top:.3rem"><button class="iconbtn" data-editc="' + esc(cm.comment_id) +
          '">Edit</button><button class="iconbtn" data-delc="' + esc(cm.comment_id) + '">Delete</button></div>' : "") +
        "</div></div>";
    }).join("") || '<p class="page-sub">No comments yet.</p>';
    var subtasks = data.subtasks.map(function (st) {
      return '<div class="subtask-row"><button class="checkbox' + (st.completed ? " on" : "") +
        '" data-subdone="' + esc(st.task_id) + '">✓</button><span class="tname">' + esc(st.name) + "</span>" +
        (st.due_date ? '<span class="due tmeta">' + fmtDate(st.due_date) + "</span>" : "") + "</div>";
    }).join("");
    var deps = data.dependencies.map(function (dp) {
      return '<div class="dep-row">⛓ Blocked by <button type="button" class="text-button" data-opentask="' +
        esc(dp.depends_on_task_id) + '">' + esc(dp.name) + '</button><button class="iconbtn" data-deldep="' +
        esc(dp.depends_on_task_id) + '" title="Remove">✕</button></div>';
    }).join("");
    var blocking = data.blocking.map(function (dp) {
      return '<div class="dep-row">⛔ Blocking <button type="button" class="text-button" data-opentask="' +
        esc(dp.task_id) + '">' + esc(dp.name) + "</button></div>";
    }).join("");
    var atts = data.attachments.map(function (a) {
      return '<div class="dep-row">📎 <a href="/api/attachments/' + esc(a.attachment_id) + '">' + esc(a.filename) +
        "</a> <span class='tmeta'>(" + Math.round(a.size_bytes / 1024) + " KB)</span></div>";
    }).join("");
    var acts = data.activity.map(function (a) {
      return '<div class="activity-item">' + esc(a.display_name) + " " + esc(a.verb) + " · " + ago(a.created_at) + "</div>";
    }).join("");
    pane.innerHTML =
      '<div class="pane-top">' +
      '<button class="tbtn' + (t.completed ? " on" : "") + '" id="tp-complete">' +
      (t.completed ? "✓ Completed" : "○ Mark complete") + "</button>" +
      '<span class="spacer"></span>' +
      '<button class="iconbtn" id="tp-delete" title="Delete task">🗑</button>' +
      '<button class="iconbtn" id="tp-close" aria-label="Close">✕</button></div>' +
      '<div class="pane-body">' +
      '<h2 contenteditable="true" id="tp-name" spellcheck="false">' + esc(t.name) + "</h2>" +
      (data.project ? '<div class="frow"><span class="flabel">Project</span><a data-nav href="/app/project/' +
        esc(data.project.project_id) + '"><span class="chip">' + esc(data.project.name) + "</span></a></div>" : "") +
      '<div class="frow"><span class="flabel">Assignee</span><select id="tp-assignee">' + mopts + "</select></div>" +
      '<div class="frow"><span class="flabel">Start date</span><input type="date" id="tp-start" value="' + esc(t.start_date || "") + '"></div>' +
      '<div class="frow"><span class="flabel">Due date</span><input type="date" id="tp-due" value="' + esc(t.due_date || "") + '"></div>' +
      '<div class="frow"><span class="flabel">Priority</span><select id="tp-priority">' +
      ["", "Low", "Medium", "High"].map(function (p) {
        return '<option value="' + p + '"' + ((t.priority || "") === p ? " selected" : "") + ">" + (p || "None") + "</option>";
      }).join("") + "</select></div>" +
      '<div class="frow"><span class="flabel">Status</span><select id="tp-status">' +
      [["", "None"], ["On track", "On track"], ["At risk", "At risk"], ["Off track", "Off track"]].map(function (s) {
        return '<option value="' + s[0] + '"' + ((t.task_status || "") === s[0] ? " selected" : "") + ">" + s[1] + "</option>";
      }).join("") + "</select></div>" +
      '<div class="subhead">Description</div>' +
      '<textarea class="notes-box" id="tp-notes" placeholder="What is this task about?">' + esc(t.notes) + "</textarea>" +
      '<div class="subhead">Subtasks</div>' + subtasks +
      '<div class="addtask-row"><button class="tbtn" id="tp-addsub">＋ Add subtask</button></div>' +
      '<div class="subhead">Dependencies</div>' + (deps + blocking || '<p class="page-sub">None.</p>') +
      '<div class="addtask-row"><button class="tbtn" id="tp-adddep">＋ Add dependency</button></div>' +
      '<div class="subhead">Attachments</div>' + (atts || '<p class="page-sub">No attachments.</p>') +
      '<div class="addtask-row"><label class="tbtn">📎 Attach file<input type="file" id="tp-file" hidden></label></div>' +
      '<div class="subhead">Comments</div>' + comments +
      '<div class="comment-box">' + avatar(ME.user.display_name, ME.user.avatar_color, ME.user.initials, true) +
      '<textarea id="tp-comment" placeholder="Add a comment. Use @Name to mention."></textarea></div>' +
      '<div class="modal-actions"><button class="tbtn primary" id="tp-comment-send">Comment</button></div>' +
      '<div class="subhead">Activity</div>' + (acts || '<p class="page-sub">No activity.</p>') +
      "</div>";

    var tid = t.task_id;
    async function patch(body, refresh) {
      try {
        await api("/tasks/" + tid, { method: "PATCH", body: body });
        if (refresh !== false) { route(); }
      } catch (e) {
        if (e.code === "blocked") {
          if (confirm(e.message + " Complete it anyway?")) {
            await api("/tasks/" + tid, { method: "PATCH", body: Object.assign({ force: true }, body) });
            route(); return;
          }
        } else { toast(e.message, true); }
      }
      openTask(tid);
    }
    pane.querySelector("#tp-close").onclick = closePane;
    pane.querySelector("#tp-complete").onclick = function () { patch({ completed: t.completed ? 0 : 1 }); };
    pane.querySelector("#tp-delete").onclick = async function () {
      if (!confirm("Delete this task? It moves to trash and can be restored.")) return;
      await api("/tasks/" + tid, { method: "DELETE" });
      closePane(); toast("Task moved to trash"); route();
    };
    pane.querySelector("#tp-name").addEventListener("blur", function () {
      var name = this.textContent.trim();
      if (name && name !== t.name) patch({ name: name }, false);
    });
    pane.querySelector("#tp-assignee").onchange = function () { patch({ assignee_user_id: this.value || null }); };
    pane.querySelector("#tp-start").onchange = function () { patch({ start_date: this.value || null }); };
    pane.querySelector("#tp-due").onchange = function () { patch({ due_date: this.value || null }); };
    pane.querySelector("#tp-priority").onchange = function () { patch({ priority: this.value || null }); };
    pane.querySelector("#tp-status").onchange = function () { patch({ task_status: this.value || null }); };
    pane.querySelector("#tp-notes").addEventListener("blur", function () {
      if (this.value !== t.notes) patch({ notes: this.value }, false);
    });
    pane.querySelector("#tp-addsub").onclick = async function () {
      var name = prompt("Subtask name");
      if (!name || !name.trim()) return;
      await api("/tasks", { method: "POST", body: { name: name.trim(), parent_task_id: tid } });
      openTask(tid);
    };
    pane.querySelector("#tp-adddep").onclick = async function () {
      var q = prompt("Type part of the blocking task's name");
      if (!q) return;
      var res = await api("/search?q=" + encodeURIComponent(q.trim()));
      var cand = res.tasks.filter(function (x) { return x.task_id !== tid; })[0];
      if (!cand) { toast("No matching task found", true); return; }
      if (!confirm('Add "' + cand.name + '" as a dependency?')) return;
      try {
        await api("/tasks/" + tid + "/dependencies", { method: "POST", body: { depends_on_task_id: cand.task_id } });
        openTask(tid);
      } catch (e) { toast(e.message, true); }
    };
    pane.querySelectorAll("[data-deldep]").forEach(function (b) {
      b.onclick = async function () {
        await api("/tasks/" + tid + "/dependencies/" + b.dataset.deldep, { method: "DELETE" });
        openTask(tid);
      };
    });
    pane.querySelectorAll("[data-subdone]").forEach(function (b) {
      b.onclick = async function () {
        await api("/tasks/" + b.dataset.subdone, { method: "PATCH", body: { completed: b.classList.contains("on") ? 0 : 1 } });
        openTask(tid);
      };
    });
    pane.querySelectorAll("[data-opentask]").forEach(function (a) {
      a.onclick = function (ev) { ev.preventDefault(); openTask(a.dataset.opentask); };
    });
    pane.querySelector("#tp-file").onchange = async function () {
      if (!this.files.length) return;
      var fd = new FormData(); fd.append("file", this.files[0]);
      try {
        await api("/tasks/" + tid + "/attachments", { method: "POST", body: fd });
        toast("Attachment uploaded"); openTask(tid);
      } catch (e) { toast(e.message, true); }
    };
    pane.querySelector("#tp-comment-send").onclick = async function () {
      var body = pane.querySelector("#tp-comment").value.trim();
      if (!body) return;
      await api("/tasks/" + tid + "/comments", { method: "POST", body: { body: body } });
      openTask(tid);
    };
    pane.querySelectorAll("[data-editc]").forEach(function (b) {
      b.onclick = async function () {
        var nb = prompt("Edit comment");
        if (nb === null || !nb.trim()) return;
        await api("/comments/" + b.dataset.editc, { method: "PATCH", body: { body: nb.trim() } });
        openTask(tid);
      };
    });
    pane.querySelectorAll("[data-delc]").forEach(function (b) {
      b.onclick = async function () {
        if (!confirm("Delete this comment?")) return;
        await api("/comments/" + b.dataset.delc, { method: "DELETE" });
        openTask(tid);
      };
    });
  }

  // ---------------- shared task rendering ----------------
  function taskRowHtml(t, withSelect) {
    return '<div class="task-row' + (t.completed ? " done" : "") + '" data-task="' + esc(t.task_id) + '">' +
      (withSelect ? '<input type="checkbox" class="selectbox" data-select="' + esc(t.task_id) + '"' +
        (SELECTED[t.task_id] ? " checked" : "") + ' aria-label="Select task">' : "") +
      '<button class="checkbox' + (t.completed ? " on" : "") + '" data-done="' + esc(t.task_id) + '" aria-label="Toggle complete">✓</button>' +
      '<span class="tname">' + esc(t.name) + "</span>" +
      '<span class="tmeta">' +
      (t.subtask_count ? '<span title="Subtasks">↳' + t.subtask_count + "</span>" : "") +
      (t.comment_count ? '<span title="Comments">💬' + t.comment_count + "</span>" : "") +
      (t.attachment_count ? "<span>📎</span>" : "") +
      (t.priority ? '<span class="chip p-' + esc(t.priority) + '">' + esc(t.priority) + "</span>" : "") +
      (t.task_status ? '<span class="chip s-' + esc(t.task_status).replace(/ /g, "_").toLowerCase() + '">' + esc(t.task_status) + "</span>" : "") +
      (t.due_date ? '<span class="due' + dueClass(t.due_date, t.completed) + '">' + fmtDate(t.due_date) + "</span>" : "") +
      (t.assignee_name ? avatar(t.assignee_name, t.assignee_color, t.assignee_initials, true) : "") +
      "</span></div>";
  }
  function wireTaskRows(scope) {
    scope.querySelectorAll("[data-task]").forEach(function (r) {
      r.addEventListener("click", function (ev) {
        if (ev.target.closest("[data-done],[data-select]")) return;
        openTask(r.dataset.task);
      });
    });
    scope.querySelectorAll("[data-done]").forEach(function (b) {
      b.onclick = async function () {
        try {
          await api("/tasks/" + b.dataset.done, { method: "PATCH", body: { completed: b.classList.contains("on") ? 0 : 1 } });
          route();
        } catch (e) {
          if (e.code === "blocked" && confirm(e.message + " Complete it anyway?")) {
            await api("/tasks/" + b.dataset.done, { method: "PATCH", body: { completed: 1, force: true } });
            route();
          } else if (e.code !== "blocked") { toast(e.message, true); }
        }
      };
    });
    scope.querySelectorAll("[data-select]").forEach(function (cb) {
      cb.onchange = function () {
        if (cb.checked) SELECTED[cb.dataset.select] = true; else delete SELECTED[cb.dataset.select];
        updateBulkBar();
      };
    });
  }
  function bulkBarHtml() {
    var n = Object.keys(SELECTED).length;
    return '<div class="toolbar" id="bulkbar"' + (n ? "" : " hidden") + '>' +
      '<span><strong id="bulk-count">' + n + "</strong> selected</span>" +
      '<button class="tbtn" id="bulk-complete">Complete</button>' +
      '<button class="tbtn" id="bulk-assign">Assign to me</button>' +
      '<button class="tbtn" id="bulk-due">Set due date…</button>' +
      '<button class="tbtn danger" id="bulk-delete">Delete</button>' +
      '<button class="tbtn" id="bulk-clear">Clear</button></div>';
  }
  function updateBulkBar() {
    var bar = document.getElementById("bulkbar");
    if (!bar) return;
    var n = Object.keys(SELECTED).length;
    bar.hidden = !n;
    var c = document.getElementById("bulk-count");
    if (c) c.textContent = n;
  }
  function wireBulkBar() {
    var bar = document.getElementById("bulkbar");
    if (!bar) return;
    async function run(action, extra) {
      var ids = Object.keys(SELECTED);
      if (!ids.length) return;
      var r = await api("/tasks/bulk", { method: "POST", body: Object.assign({ task_ids: ids, action: action }, extra || {}) });
      SELECTED = {};
      toast(r.changed + " tasks updated"); route();
    }
    document.getElementById("bulk-complete").onclick = function () { run("complete"); };
    document.getElementById("bulk-assign").onclick = function () { run("assign", { assignee_user_id: ME.user.user_id }); };
    document.getElementById("bulk-due").onclick = function () {
      var v = prompt("Due date (YYYY-MM-DD)");
      if (v) run("set_due_date", { due_date: v });
    };
    document.getElementById("bulk-delete").onclick = function () {
      if (confirm("Move selected tasks to trash?")) run("delete");
    };
    document.getElementById("bulk-clear").onclick = function () { SELECTED = {}; route(); };
  }

  function filterBarHtml() {
    return '<div class="toolbar">' +
      '<button class="tbtn' + (FILTERS.completed === "0" ? " on" : "") + '" id="f-incomplete">Incomplete</button>' +
      '<button class="tbtn' + (FILTERS.assignee ? " on" : "") + '" id="f-mine">Just my tasks</button>' +
      '<select class="tbtn" id="f-priority"><option value="">Priority: all</option>' +
      ["High", "Medium", "Low"].map(function (p) {
        return '<option' + (FILTERS.priority === p ? " selected" : "") + ">" + p + "</option>";
      }).join("") + "</select>" +
      '<select class="tbtn" id="f-sort"><option value="manual">Sort: manual</option>' +
      [["due_date", "Due date"], ["alphabetical", "Alphabetical"], ["created", "Newest"]].map(function (s) {
        return '<option value="' + s[0] + '"' + (FILTERS.sort === s[0] ? " selected" : "") + ">Sort: " + s[1] + "</option>";
      }).join("") + "</select>" +
      '<button class="tbtn" id="f-save">☆ Save view</button>' +
      '<span class="spacer"></span></div>';
  }
  function wireFilterBar() {
    var q = function () { route(); };
    var b;
    if ((b = document.getElementById("f-incomplete"))) b.onclick = function () {
      FILTERS.completed = FILTERS.completed === "0" ? undefined : "0"; q();
    };
    if ((b = document.getElementById("f-mine"))) b.onclick = function () {
      FILTERS.assignee = FILTERS.assignee ? undefined : ME.user.user_id; q();
    };
    if ((b = document.getElementById("f-priority"))) b.onchange = function () {
      FILTERS.priority = this.value || undefined; q();
    };
    if ((b = document.getElementById("f-sort"))) b.onchange = function () {
      FILTERS.sort = this.value === "manual" ? undefined : this.value; q();
    };
    if ((b = document.getElementById("f-save"))) b.onclick = async function () {
      var name = prompt("Name this view");
      if (!name || !name.trim()) return;
      await api("/views", { method: "POST", body: { name: name.trim(), query: Object.assign({ path: location.pathname }, FILTERS) } });
      toast("View saved — find it on Home");
    };
  }
  function filterQuery() {
    var qp = new URLSearchParams();
    Object.keys(FILTERS).forEach(function (k) { if (FILTERS[k]) qp.set(k, FILTERS[k]); });
    var s = qp.toString();
    return s ? "?" + s : "";
  }

  // ---------------- views ----------------
  async function viewHome() {
    loadingPage();
    var mt, views;
    try {
      mt = await api("/my-tasks");
      views = await api("/views");
    } catch (e) { return; }
    var today = new Date().toLocaleDateString("en-US", {
      weekday: "long", month: "long", day: "numeric",
    });
    var projectRows = PROJECTS.slice(0, 1).map(function (p) {
      return '<a class="home-project-row" data-nav href="/app/project/' + esc(p.project_id) + '">' +
        '<span class="home-project-icon" style="background:' + esc(p.color) + '">☷</span>' +
        '<span class="home-project-copy"><strong>' + esc(p.name) + '</strong><span>' +
        '3 tasks due soon</span></span><span class="row-arrow" aria-hidden="true">›</span></a>';
    }).join("");
    var learnCards = [
      ["3 min", "Getting started", "Learn the basics and see how Asana helps you get work done.", "learn-tasks", "rocket"],
      ["5 min read", "Manage student organizations", "Learn how to organize meetings, events, and projects.", "learn-team", "education"],
      ["15 min", "Manage projects in Asana", "Plan, organize, and manage your projects effectively.", "learn-projects", "calendar"],
      ["5 min read", "Avoid silos with multi-homing", "Keep work visible across useful local projects.", "learn-workflow", "workflow"],
    ].map(function (card, index) {
      return '<button type="button" class="learn-card" data-learn="' + card[3] + '">' +
        '<span class="learn-graphic learn-graphic-' + (index + 1) + '" aria-hidden="true">' +
        '<img class="learn-vector" src="/static/source/learn-' + (index + 1) + '.svg" width="120" height="120" alt="">' +
        '<span class="learn-duration">' + card[0] + '</span></span><strong>' + card[1] +
        '</strong><span class="learn-copy">' + card[2] +
        '</span></button>';
    }).join("");
    setPage('<section class="home-header" aria-labelledby="home-greeting">' +
      '<time class="home-date">' + esc(today) + '</time>' +
      '<h1 id="home-greeting">' + greeting() + ', ray</h1>' +
      '<div class="home-header-actions"><div class="home-summary" aria-label="Weekly summary">' +
      '<button type="button" id="home-timeframe">My week <span aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m18.185 7.851-6.186 5.191-6.186-5.191a1.499 1.499 0 1 0-1.928 2.298l7.15 6a1.498 1.498 0 0 0 1.928 0l7.15-6a1.5 1.5 0 0 0-1.928-2.298Z"></path></svg></span></button>' +
      '<button type="button" id="home-tasks-stat"><span aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M19.439 5.439 8 16.878l-3.939-3.939A1.5 1.5 0 1 0 1.94 15.06l5 5c.293.293.677.439 1.061.439.384 0 .768-.146 1.061-.439l12.5-12.5a1.5 1.5 0 1 0-2.121-2.121h-.002Z"></path></svg></span> 0 tasks completed</button>' +
      '<button type="button" id="home-collaborators"><span aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M16,13.5c-3.59,0-6.5-2.91-6.5-6.5S12.41,.5,16,.5s6.5,2.91,6.5,6.5-2.91,6.5-6.5,6.5Zm-10,7.5c0-1.287,.348-2.492,.955-3.527,.383-.653-.122-1.473-.878-1.473h-1.076C2.239,16,0,18.239,0,21v2C0,23.552,.448,24,1,24H5c.552,0,1-.448,1-1v-2Zm18,2v-2c0-2.761-2.239-5-5-5h-6c-2.761,0-5,2.239-5,5v2c0,.552,.448,1,1,1h14c.552,0,1-.448,1-1ZM7.5,7c0-1.834,.584-3.53,1.573-4.917,.461-.646,.016-1.539-.777-1.576-.662-.031-1.351,.041-2.057,.239C3.67,1.466,1.753,3.767,1.525,6.424c-.331,3.849,2.695,7.076,6.475,7.076,.102,0,.204-.002,.305-.007,.789-.038,1.227-.933,.768-1.575-.989-1.387-1.573-3.083-1.573-4.917Z"></path></svg></span> 0 collaborators</button></div>' +
      '<button type="button" class="home-customize" id="home-customize"><span aria-hidden="true">▦</span> Customize</button></div>' +
      '</section><div class="home-list">' +
      '<section class="home-section home-my-tasks" aria-labelledby="home-my-tasks-title"><div class="home-card">' +
      '<div class="home-task-head"><div class="home-title-row">' +
      '<span class="avatar home-avatar" style="background:#a88ff0" aria-hidden="true">QA</span>' +
      '<h2 id="home-my-tasks-title"><a data-nav href="/app/tasks">My tasks</a></h2><span class="home-lock" aria-hidden="true">▣</span>' +
      '<button type="button" class="home-more" id="home-task-options" aria-label="My tasks options">•••</button>' +
      '</div><div class="home-task-tabs" role="tablist" aria-label="Task status">' +
      '<button role="tab" aria-selected="true" class="active" data-home-tab="upcoming">Upcoming</button>' +
      '<button role="tab" aria-selected="false" data-home-tab="overdue">Overdue</button>' +
      '<button role="tab" aria-selected="false" data-home-tab="completed">Completed</button>' +
      '</div></div><div class="home-task-panel" id="home-task-panel" role="tabpanel"></div>' +
      '</div></section>' +
      '<section class="home-section home-projects" aria-labelledby="home-projects-title"><div class="home-card">' +
      '<div class="home-project-head"><h2 id="home-projects-title"><a data-nav href="/app/projects">Projects</a></h2>' +
      '<button type="button" class="home-project-view" id="home-project-view">Recents <span aria-hidden="true">⌄</span></button>' +
      '<button type="button" class="home-more" id="home-project-options" aria-label="Project options">•••</button></div>' +
      '<div class="home-project-list"><button type="button" class="home-project-create" id="home-new-project">' +
      '<span aria-hidden="true">＋</span><strong>Create project</strong></button>' +
      (projectRows || '<p class="home-empty">No projects yet.</p>') + '</div>' +
      '</div></section>' +
      '<section class="home-section home-learn" aria-labelledby="home-learn-title"><div class="home-card">' +
      '<h2 id="home-learn-title"><span>Learn Asana</span></h2><div class="learn-carousel" aria-label="Learn Asana carousel">' +
      '<div class="learn-track">' + learnCards + '</div></div></div></section>' +
      '<section class="home-section home-widget home-assigned" aria-labelledby="home-assigned-title"><div class="home-card widget-card">' +
      '<div class="widget-head"><div><h2 id="home-assigned-title">Tasks I\'ve assigned</h2>' +
      '<p>Track delegated work and see what needs attention.</p></div><button type="button" class="home-more" data-widget="assigned" aria-label="Assigned task options">•••</button></div>' +
      '<div class="widget-rows"><button type="button"><span>○</span><strong>Define project milestones</strong><time>Yesterday</time></button>' +
      '<button type="button"><span>○</span><strong>Draft initial project plan</strong><time>Today</time></button>' +
      '<button type="button"><span>○</span><strong>Outline next steps</strong><time>Tomorrow</time></button>' +
      '<button type="button"><span>○</span><strong>Research best practices</strong><time>Wednesday</time></button></div></div></section>' +
      '<section class="home-section home-widget home-people" aria-labelledby="home-people-title"><div class="home-card widget-card">' +
      '<div class="widget-head"><div><h2 id="home-people-title">People</h2><p>See who is on track and who needs support.</p></div>' +
      '<button type="button" class="home-more" data-widget="people" aria-label="People options">•••</button></div>' +
      '<div class="people-grid"><button type="button"><span class="widget-avatar blue">MP</span><strong>Project partner</strong><small>2 upcoming</small></button>' +
      '<button type="button"><span class="widget-avatar pink">DS</span><strong>Design teammate</strong><small>1 overdue</small></button>' +
      '<button type="button"><span class="widget-avatar green">QA</span><strong>Quality reviewer</strong><small>3 completed</small></button></div></div></section>' +
      '<section class="home-section home-widget home-focus" aria-labelledby="home-focus-title"><div class="home-card widget-card focus-card">' +
      '<div class="widget-head"><div><h2 id="home-focus-title">Focus for this week</h2><p>Keep a small, deterministic local plan visible.</p></div>' +
      '<button type="button" class="home-more" data-widget="focus" aria-label="Focus options">•••</button></div>' +
      '<div class="focus-steps"><button type="button"><span>1</span><strong>Review priorities</strong></button>' +
      '<button type="button"><span>2</span><strong>Share a progress update</strong></button>' +
      '<button type="button"><span>3</span><strong>Plan the next milestone</strong></button></div></div></section></div>', "home-page");

    function renderHomeTasks(kind) {
      var iso = new Date().toISOString().slice(0, 10);
      var tasks = mt.tasks.filter(function (task) {
        if (kind === "completed") return Boolean(task.completed);
        if (task.completed) return false;
        if (kind === "overdue") return Boolean(task.due_date && task.due_date < iso);
        return true;
      }).slice(0, 2);
      var panel = document.getElementById("home-task-panel");
      var homeRows = tasks.map(function (task) {
        return '<div class="task-row' + (task.completed ? ' done' : '') + '" data-task="' + esc(task.task_id) + '">' +
          '<button class="checkbox' + (task.completed ? ' on' : '') + '" data-done="' + esc(task.task_id) + '" aria-label="Toggle complete">✓</button>' +
          '<span class="tname">' + esc(task.name) + '</span><span class="home-project-chip"><i></i>Demo</span>' +
          '<span class="home-due">' + (task.due_date ? fmtDate(task.due_date) : 'This week') + '</span></div>';
      }).join("");
      panel.innerHTML = '<button type="button" class="home-task-create" id="home-add-task">＋ Create task</button>' +
        '<div class="home-task-rows">' + (homeRows || '<div class="home-empty"><strong>You\'re all caught up</strong><span>No ' +
        kind + ' tasks in this local workspace.</span></div>') + '</div>';
      wireTaskRows(panel);
      document.getElementById("home-add-task").onclick = function () { openTaskModal(); };
    }
    renderHomeTasks("upcoming");
    document.querySelectorAll("[data-home-tab]").forEach(function (tab) {
      tab.onclick = function () {
        document.querySelectorAll("[data-home-tab]").forEach(function (item) {
          var selected = item === tab;
          item.classList.toggle("active", selected);
          item.setAttribute("aria-selected", String(selected));
        });
        renderHomeTasks(tab.dataset.homeTab);
      };
    });
    document.getElementById("home-new-project").onclick = function () { openProjectModal(); };
    document.getElementById("home-project-view").onclick = function () { openHomeOptions("project-view"); };
    document.getElementById("home-project-options").onclick = function () { openHomeOptions("projects"); };
    document.getElementById("home-customize").onclick = openCustomizeHome;
    document.getElementById("home-timeframe").onclick = function () { toast("My week selected"); };
    document.getElementById("home-tasks-stat").onclick = function () { nav("/app/tasks"); };
    document.getElementById("home-collaborators").onclick = function () { nav("/app/invite"); };
    document.getElementById("home-task-options").onclick = function () { openSavedViews(views.views); };
    document.querySelectorAll("[data-learn]").forEach(function (card) {
      card.onclick = function () { openLearnDetail(card.dataset.learn); };
    });
    document.querySelectorAll("[data-widget]").forEach(function (button) {
      button.onclick = function () { openHomeOptions(button.dataset.widget); };
    });
    document.querySelectorAll(".widget-rows button,.people-grid button,.focus-steps button").forEach(function (button) {
      button.onclick = function () { openWidgetDetail(button); };
    });
  }

  function openHomeOptions(kind) {
    var config = {
      "project-view": ["Project view", "Choose which projects appear on Home.", [["Recent projects", "/app/projects"], ["All projects", "/app/projects"]]],
      projects: ["Project options", "Open or create projects from Home.", [["Open projects", "/app/projects"], ["Create project", "create-project"]]],
      assigned: ["Assigned task options", "Review tasks you have delegated.", [["Open My tasks", "/app/tasks"], ["Customize Home", "customize"]]],
      people: ["People options", "See teammates and team activity.", [["Open People", "/app/people"], ["Browse teams", "/app/people/teams"]]],
      focus: ["Focus options", "Connect this week’s priorities to strategy.", [["Open Strategy", "/app/strategy"], ["Customize Home", "customize"]]],
    }[kind];
    var actions = config[2].map(function (item) {
      return '<button class="tbtn" data-home-option="' + esc(item[1]) + '">' + esc(item[0]) + '</button>';
    }).join("");
    openModal('<h2>' + config[0] + '</h2><p class="page-sub">' + config[1] + '</p><div class="home-option-list">' + actions + '</div>');
    document.querySelectorAll("[data-home-option]").forEach(function (button) {
      button.onclick = function () {
        var target = button.dataset.homeOption;
        closeModal();
        if (target === "create-project") openProjectModal();
        else if (target === "customize") openCustomizeHome();
        else nav(target);
      };
    });
  }

  function openWidgetDetail(button) {
    var title = button.querySelector("strong");
    var widget = button.closest(".home-assigned") ? "assigned" : button.closest(".home-people") ? "people" : "focus";
    var target = widget === "assigned" ? "/app/tasks" : widget === "people" ? "/app/people" : "/app/strategy";
    openModal('<h2>' + esc(title ? title.textContent : "Home item") + '</h2><p class="page-sub">Review this item in its related workspace area.</p>' +
      '<div class="modal-actions"><button class="tbtn" id="widget-close">Close</button><button class="tbtn primary" id="widget-open">Open related work</button></div>');
    document.getElementById("widget-close").onclick = closeModal;
    document.getElementById("widget-open").onclick = function () { closeModal(); nav(target); };
  }

  function openCustomizeHome() {
    openModal('<h2>Customize Home</h2><p class="page-sub">Choose a comfortable local layout for this device.</p>' +
      '<div class="assistant-prompts"><button class="tbtn" data-density="comfortable">Comfortable</button>' +
      '<button class="tbtn" data-density="compact">Compact</button>' +
      '<button class="tbtn" data-density="default">Reset</button></div>' +
      '<p id="customize-result" class="assistant-answer" aria-live="polite"></p>');
    document.querySelectorAll("[data-density]").forEach(function (button) {
      button.onclick = function () {
        document.body.dataset.homeDensity = button.dataset.density;
        localStorage.setItem("asana-home-density", button.dataset.density);
        document.getElementById("customize-result").textContent = "Home layout updated locally.";
      };
    });
  }

  function openAchievements() {
    openModal('<h2>Local achievements</h2><div class="achievement-list">' +
      '<p><span aria-hidden="true">✓</span><strong>Home explorer</strong><br>Opened your synthetic workspace.</p>' +
      '<p><span aria-hidden="true">◇</span><strong>Project starter</strong><br>Create a local project to continue.</p>' +
      '</div>');
  }

  function openSavedViews(savedViews) {
    var rows = savedViews.map(function (view) {
      var query = JSON.parse(view.query_json || "{}");
      return '<button type="button" class="saved-view-row" data-saved-view=\'' +
        esc(JSON.stringify(query)) + "'>☆ " + esc(view.name) + '</button>';
    }).join("");
    openModal('<h2>My tasks</h2><p class="page-sub">Open My tasks or one of your locally saved views.</p>' +
      (rows || '<p>No saved views yet.</p>') +
      '<div class="modal-actions"><button class="tbtn primary" id="open-my-tasks">Open My tasks</button></div>');
    document.getElementById("open-my-tasks").onclick = function () { closeModal(); nav("/app/tasks"); };
    document.querySelectorAll("[data-saved-view]").forEach(function (button) {
      button.onclick = function () {
        var query = JSON.parse(button.dataset.savedView);
        FILTERS = {};
        ["completed", "assignee", "priority", "sort"].forEach(function (key) {
          if (query[key]) FILTERS[key] = query[key];
        });
        closeModal(); nav(query.path || "/app/tasks");
      };
    });
  }

  function openLearnDetail(topic) {
    var detail = {
      "learn-tasks": ["Get started with My tasks", "Use Upcoming, Overdue, and Completed to keep your local day clear."],
      "learn-projects": ["Build your first project", "Create a project, choose a local template, and assign synthetic work."],
      "learn-team": ["Collaborate with your team", "Invite synthetic teammates and keep comments attached to local tasks."],
      "learn-workflow": ["Try a useful workflow", "Open Projects to create a deterministic local workflow."],
    }[topic];
    openModal('<h2>' + esc(detail[0]) + '</h2><p>' + esc(detail[1]) + '</p>' +
      '<div class="modal-actions"><button class="tbtn" id="learn-close">Close</button>' +
      '<button class="tbtn primary" id="learn-open">Open related work</button></div>');
    document.getElementById("learn-close").onclick = closeModal;
    document.getElementById("learn-open").onclick = function () {
      closeModal(); nav(topic === "learn-tasks" ? "/app/tasks" : "/app/projects");
    };
  }

  async function viewMyTasks(dueState) {
    loadingPage();
    var data;
    var query = new URLSearchParams(filterQuery().replace(/^\?/, ""));
    var today = new Date();
    var iso = today.toISOString().slice(0, 10);
    if (dueState === "upcoming") query.set("due_after", iso);
    if (dueState === "overdue") {
      today.setDate(today.getDate() - 1);
      query.set("due_before", today.toISOString().slice(0, 10));
      query.set("completed", "0");
    }
    try { data = await api("/my-tasks" + (query.toString() ? "?" + query : "")); } catch (e) { return; }
    var rows = data.tasks.map(function (t) { return taskRowHtml(t, true); }).join("");
    setPage('<div class="page-head">' + avatar(ME.user.display_name, ME.user.avatar_color, ME.user.initials) +
      "<h1>" + (dueState === "upcoming" ? "Upcoming" : dueState === "overdue" ? "Overdue" : "My tasks") +
      "</h1></div>" + filterBarHtml() + bulkBarHtml() +
      '<div class="tasklist">' + (rows ||
        '<div class="empty"><div class="art">✅</div><h3>No tasks match</h3><p>Change the filters or create a task.</p></div>') +
      "</div>" +
      '<div class="addtask-row"><button class="tbtn" id="mt-add">＋ Add task</button></div>');
    wireFilterBar(); wireBulkBar(); wireTaskRows(document.getElementById("page"));
    document.getElementById("mt-add").onclick = function () { openTaskModal(); };
  }

  async function viewProjects() {
    var cards = PROJECTS.map(function (p) {
      return '<div class="gcard" data-navcard="/app/project/' + esc(p.project_id) + '">' +
        '<span class="proj-icon" style="background:' + esc(p.color) + '">≡</span>' +
        '<h3>' + esc(p.name) + '</h3><div class="gsub">' + p.task_count + ' tasks</div></div>';
    }).join("");
    setPage('<div class="page-head"><h1>Projects</h1><span class="spacer"></span>' +
      '<button class="tbtn primary" id="projects-create">Create project</button></div>' +
      '<div class="grid-cards">' + (cards || '<div class="empty"><h3>No projects yet</h3></div>') + '</div>');
    document.getElementById("projects-create").onclick = openProjectModal;
    document.querySelectorAll("[data-navcard]").forEach(function (card) {
      card.onclick = function () { nav(card.dataset.navcard); };
    });
  }

  function viewAgents(section) {
    var body;
    if (section === "library") {
      body = '<div class="page-head"><h1>Agent library</h1><span class="spacer"></span><button class="tbtn primary" data-agent-action="Create agent">Create agent</button></div>' +
        '<p class="page-sub">Choose an agent pattern for repeatable work in this workspace.</p><div class="grid-cards mode-card-grid">' +
        '<button class="gcard mode-card" data-agent-action="Project status agent"><span class="mode-card-icon">✦</span><h3>Project status agent</h3><p>Summarize progress, risks, and next steps.</p></button>' +
        '<button class="gcard mode-card" data-agent-action="Work intake agent"><span class="mode-card-icon">↳</span><h3>Work intake agent</h3><p>Organize requests and route new work.</p></button>' +
        '<button class="gcard mode-card" data-agent-action="Campaign agent"><span class="mode-card-icon">◎</span><h3>Campaign agent</h3><p>Coordinate briefs, reviews, and launches.</p></button></div>';
    } else if (section === "activity") {
      body = '<div class="page-head"><h1>Agent activity</h1></div><p class="page-sub">Review local actions proposed by your AI teammates.</p>' +
        '<div class="settings-block"><h3>Today</h3><div class="inbox-item"><span>✦</span><div><strong>Project status agent</strong><p>Prepared a local weekly status summary.</p><span class="when">A few minutes ago</span></div></div>' +
        '<div class="inbox-item"><span>◎</span><div><strong>Campaign agent</strong><p>Suggested owners for two upcoming milestones.</p><span class="when">Earlier today</span></div></div></div>';
    } else {
      body = '<div class="mode-hero"><span class="mode-card-icon large">✦</span><div><p class="mode-eyebrow">AGENTS</p><h1>AI teammates for your team’s work</h1><p>Create, manage, and monitor agents without mixing them into your Inbox.</p></div></div>' +
        '<div class="grid-cards mode-card-grid"><button class="gcard mode-card" data-go="/app/agents/library"><h3>Explore the agent library</h3><p>Start from a role designed for common workflows.</p><span>Browse agents →</span></button>' +
        '<button class="gcard mode-card" data-go="/app/agents/activity"><h3>Review agent activity</h3><p>See recent local suggestions and summaries.</p><span>View activity →</span></button>' +
        '<button class="gcard mode-card" data-agent-action="Create agent"><h3>Create an agent</h3><p>Define a role and the work it should support.</p><span>Get started →</span></button></div>';
    }
    setPage(body, "mode-page");
    document.querySelectorAll("[data-go]").forEach(function (button) { button.onclick = function () { nav(button.dataset.go); }; });
    document.querySelectorAll("[data-agent-action]").forEach(function (button) {
      button.onclick = function () {
        openModal('<h2>' + esc(button.dataset.agentAction) + '</h2><p class="page-sub">Configure this agent for the current local workspace.</p>' +
          '<div class="field"><label>Instructions</label><textarea rows="4" placeholder="Describe the work this agent should help with"></textarea></div>' +
          '<div class="modal-actions"><button class="tbtn" data-close-modal>Cancel</button><button class="tbtn primary" id="agent-save">Save draft</button></div>');
        document.querySelector("[data-close-modal]").onclick = closeModal;
        document.getElementById("agent-save").onclick = function () { closeModal(); toast("Agent draft saved locally"); };
      };
    });
  }

  function viewStrategy(section) {
    if (section === "reporting") { viewActivity(); return; }
    setPage('<div class="mode-hero strategy-hero"><span class="mode-card-icon large">▲</span><div><p class="mode-eyebrow">STRATEGY</p>' +
      '<h1>Connect goals to the work that drives them</h1><p>Move between an overview, goals, portfolios, and reporting from the Strategy sidebar.</p></div></div>' +
      '<div class="grid-cards mode-card-grid"><button class="gcard mode-card" data-go="/app/goals"><h3>Goals</h3><p>Set measurable outcomes and update progress.</p><span>Open goals →</span></button>' +
      '<button class="gcard mode-card" data-go="/app/portfolios"><h3>Portfolios</h3><p>Monitor related projects in one place.</p><span>Open portfolios →</span></button>' +
      '<button class="gcard mode-card" data-go="/app/strategy/reporting"><h3>Reporting</h3><p>Review workspace activity and delivery signals.</p><span>Open reporting →</span></button></div>', "mode-page");
    document.querySelectorAll("[data-go]").forEach(function (button) { button.onclick = function () { nav(button.dataset.go); }; });
  }

  function viewKnowledge(section) {
    var cards;
    if (section === "collections") {
      cards = '<button class="gcard knowledge-card" data-knowledge="Project playbooks"><h3>Project playbooks</h3><p>Shared guidance for planning, reviews, and handoffs.</p></button>' +
        '<button class="gcard knowledge-card" data-knowledge="Team policies"><h3>Team policies</h3><p>Workspace norms and decision records.</p></button>' +
        '<button class="gcard knowledge-card" data-knowledge="Launch notes"><h3>Launch notes</h3><p>Reusable context for upcoming releases.</p></button>';
    } else if (section === "templates") {
      cards = '<button class="gcard knowledge-card" data-knowledge="Project brief"><h3>Project brief</h3><p>Capture goals, scope, owners, and milestones.</p></button>' +
        '<button class="gcard knowledge-card" data-knowledge="Meeting notes"><h3>Meeting notes</h3><p>Record decisions and action items.</p></button>' +
        '<button class="gcard knowledge-card" data-knowledge="Decision log"><h3>Decision log</h3><p>Keep important choices easy to find.</p></button>';
    } else {
      cards = '<button class="gcard knowledge-card" data-knowledge="Getting started"><h3>Getting started</h3><p>Learn how work, projects, and goals fit together.</p></button>' +
        '<button class="gcard knowledge-card" data-go="/app/knowledge/collections"><h3>Collections</h3><p>Browse organized team knowledge.</p><span>View collections →</span></button>' +
        '<button class="gcard knowledge-card" data-go="/app/knowledge/templates"><h3>Templates</h3><p>Create consistent docs and project context.</p><span>View templates →</span></button>';
    }
    setPage('<div class="page-head"><h1>Knowledge</h1></div><p class="page-sub">Search shared guidance without leaving your workspace.</p>' +
      '<div class="knowledge-search"><input id="knowledge-search" type="search" placeholder="Search knowledge" aria-label="Search knowledge"></div>' +
      '<div class="grid-cards mode-card-grid" id="knowledge-results">' + cards + '</div>', "mode-page");
    document.querySelectorAll("[data-go]").forEach(function (button) { button.onclick = function () { nav(button.dataset.go); }; });
    document.querySelectorAll("[data-knowledge]").forEach(function (button) {
      button.onclick = function () { openModal('<h2>' + esc(button.dataset.knowledge) + '</h2><p>This local knowledge item is ready to use with your team’s work.</p>'); };
    });
    document.getElementById("knowledge-search").oninput = function () {
      var query = this.value.trim().toLowerCase();
      document.querySelectorAll("#knowledge-results .knowledge-card").forEach(function (card) {
        card.hidden = Boolean(query && card.textContent.toLowerCase().indexOf(query) < 0);
      });
    };
  }

  async function viewPeople(section) {
    loadingPage();
    var data;
    try { data = await api("/members"); } catch (e) { return; }
    var memberCards = data.members.map(function (member) {
      return '<button class="gcard people-card" data-member-name="' + esc(member.display_name) + '" data-member-email="' + esc(member.email) + '">' +
        avatar(member.display_name, member.avatar_color, member.initials) + '<h3>' + esc(member.display_name) + '</h3><p>' + esc(member.email) + '</p><span>View profile →</span></button>';
    }).join("");
    var body = section === "teams" ?
      '<div class="page-head"><h1>Teams</h1><span class="spacer"></span><button class="tbtn primary" id="people-invite">Invite people</button></div>' +
      '<p class="page-sub">Organize workspace members around shared work.</p><div class="grid-cards mode-card-grid">' +
      '<button class="gcard mode-card" data-team="Product"><h3>Product</h3><p>' + data.members.length + ' members · 2 projects</p></button>' +
      '<button class="gcard mode-card" data-team="Operations"><h3>Operations</h3><p>1 member · 1 project</p></button>' +
      '<button class="gcard mode-card" data-team="Marketing"><h3>Marketing</h3><p>1 member · 2 projects</p></button></div>' :
      '<div class="page-head"><h1>People</h1><span class="spacer"></span><button class="tbtn primary" id="people-invite">Invite people</button></div>' +
      '<p class="page-sub">Find teammates, see their workspace details, and move into team views.</p><div class="people-tools"><input type="search" id="people-search" placeholder="Search people" aria-label="Search people"><button class="tbtn" data-go="/app/people/teams">Browse teams</button></div>' +
      '<div class="grid-cards people-directory" id="people-directory">' + memberCards + '</div>';
    setPage(body, "mode-page");
    document.getElementById("people-invite").onclick = function () { nav("/app/invite"); };
    document.querySelectorAll("[data-go]").forEach(function (button) { button.onclick = function () { nav(button.dataset.go); }; });
    document.querySelectorAll("[data-member-name]").forEach(function (button) {
      button.onclick = function () { openModal('<h2>' + esc(button.dataset.memberName) + '</h2><p class="page-sub">' + esc(button.dataset.memberEmail) + '</p><p>Workspace member in Demo Workspace.</p>'); };
    });
    document.querySelectorAll("[data-team]").forEach(function (button) {
      button.onclick = function () { openModal('<h2>' + esc(button.dataset.team) + '</h2><p>Review this team’s members and active work from the local workspace.</p>'); };
    });
    var peopleSearch = document.getElementById("people-search");
    if (peopleSearch) peopleSearch.oninput = function () {
      var query = this.value.trim().toLowerCase();
      document.querySelectorAll("#people-directory .people-card").forEach(function (card) {
        card.hidden = Boolean(query && card.textContent.toLowerCase().indexOf(query) < 0);
      });
    };
  }

  function viewMore() {
    setPage('<div class="page-head"><h1>More</h1></div><p class="page-sub">Workspace administration and personal settings.</p>' +
      '<div class="grid-cards mode-card-grid"><button class="gcard mode-card" data-go="/app/settings"><h3>My settings</h3><p>Profile, notifications, display, and security.</p></button>' +
      '<button class="gcard mode-card" data-go="/app/admin"><h3>Workspace settings</h3><p>Members, roles, and workspace details.</p></button>' +
      '<button class="gcard mode-card" data-go="/app/billing"><h3>Billing</h3><p>Review the local sandbox plan.</p></button>' +
      '<button class="gcard mode-card" data-go="/app/trash"><h3>Trash</h3><p>Restore or permanently remove local work.</p></button></div>', "mode-page");
    document.querySelectorAll("[data-go]").forEach(function (button) { button.onclick = function () { nav(button.dataset.go); }; });
  }

  async function viewInvite() {
    var data;
    try { data = await api("/members"); } catch (e) { return; }
    var members = data.members.map(function (member) {
      return '<div class="dep-row">' + avatar(member.display_name, member.avatar_color, member.initials) +
        '<span><strong>' + esc(member.display_name) + '</strong><br><span class="gsub">' +
        esc(member.email) + '</span></span></div>';
    }).join("");
    setPage('<div class="page-head"><h1>Invite</h1></div><div class="settings-block">' +
      '<h3>Invite a teammate</h3><p class="page-sub">Invitations stay inside this offline clone.</p>' +
      '<div class="field"><label for="invite-email">Email address</label>' +
      '<input id="invite-email" type="email" placeholder="teammate@example.com"></div>' +
      '<button class="tbtn primary" id="invite-send">Send invite</button>' +
      '<p class="form-error" id="invite-error" role="alert" hidden></p></div>' +
      '<div class="settings-block"><h3>Workspace members</h3>' + members + '</div>');
    document.getElementById("invite-send").onclick = async function () {
      var email = document.getElementById("invite-email").value.trim();
      var error = document.getElementById("invite-error");
      error.hidden = true;
      try {
        await api("/invites", { method: "POST", body: { email: email } });
        toast("Invite recorded locally"); route();
      } catch (e) { error.textContent = e.message; error.hidden = false; }
    };
  }

  async function viewProject(projectId, tab) {
    loadingPage();
    var meta, tdata;
    try {
      meta = await api("/projects/" + projectId);
      tdata = await api("/projects/" + projectId + "/tasks" + filterQuery());
    } catch (e) {
      setPage('<div class="empty"><div class="art">🔍</div><h3>Project not found</h3>' +
        '<p>It may have been deleted. <a data-nav href="/app/home">Go home</a></p></div>');
      return;
    }
    var p = meta.project;
    tab = tab || p.default_view || "list";
    if (p.deleted_at) {
      setPage('<div class="empty"><div class="art">🗑</div><h3>' + esc(p.name) + ' is in the trash</h3>' +
        '<p><button class="tbtn" id="restore-p">Restore project</button></p></div>');
      document.getElementById("restore-p").onclick = async function () {
        await api("/trash/restore", { method: "POST", body: { project_id: p.project_id } });
        await loadProjects(); route();
      };
      return;
    }
    var tabs = ["overview", "list", "board", "calendar", "timeline", "files"].map(function (tb) {
      return '<button class="tab' + (tb === tab ? " active" : "") + '" data-tab="' + tb + '">' +
        tb.charAt(0).toUpperCase() + tb.slice(1) + "</button>";
    }).join("");
    var statusChip = '<span class="chip s-' + esc(p.status) + '">' +
      esc({ on_track: "On track", at_risk: "At risk", off_track: "Off track", on_hold: "On hold", complete: "Complete" }[p.status] || p.status) + "</span>";
    var head = '<div class="page-head">' +
      '<span class="proj-icon" style="background:' + esc(p.color) + '">≡</span>' +
      "<h1>" + esc(p.name) + "</h1>" +
      '<button class="iconbtn" id="p-star" title="Star project">' + (p.starred ? "★" : "☆") + "</button>" +
      statusChip +
      '<span class="spacer" style="flex:1"></span>' +
      '<button class="tbtn" id="p-share">Share</button>' +
      '<button class="tbtn" id="p-more">⋯</button></div>' +
      '<div class="tabs">' + tabs + "</div>";
    var body = "";
    if (tab === "overview") body = projectOverviewHtml(meta);
    else if (tab === "board") body = boardHtml(meta, tdata);
    else if (tab === "calendar") body = calendarHtml(tdata);
    else if (tab === "timeline") body = timelineHtml(tdata);
    else if (tab === "files") body = filesHtml(meta, tdata);
    else body = filterBarHtml() + bulkBarHtml() + listHtml(meta, tdata);
    setPage(head + body);
    document.querySelectorAll("[data-tab]").forEach(function (b) {
      b.onclick = function () { nav("/app/project/" + projectId + "/" + b.dataset.tab); };
    });
    document.getElementById("p-star").onclick = async function () {
      await api("/projects/" + projectId, { method: "PATCH", body: { starred: p.starred ? 0 : 1 } });
      route();
    };
    document.getElementById("p-share").onclick = function () { openShareModal(meta); };
    document.getElementById("p-more").onclick = function () { openProjectMenu(meta); };
    if (tab === "list") { wireFilterBar(); wireBulkBar(); }
    wireProjectBody(meta, tab);
  }

  function listHtml(meta, tdata) {
    var bySection = {};
    tdata.tasks.forEach(function (t) { (bySection[t.section_id] = bySection[t.section_id] || []).push(t); });
    var out = '<div class="tasklist">';
    meta.sections.forEach(function (s) {
      var ts = bySection[s.section_id] || [];
      out += '<div class="section-row"><span>' + esc(s.name) + '</span><span class="count">' + ts.length + "</span>" +
        '<span class="spacer" style="flex:1"></span>' +
        '<button class="iconbtn" data-rename-sec="' + esc(s.section_id) + '" title="Rename section">✎</button>' +
        '<button class="iconbtn" data-del-sec="' + esc(s.section_id) + '" title="Delete section">🗑</button></div>';
      out += ts.map(function (t) { return taskRowHtml(t, true); }).join("");
      out += '<div class="addtask-row"><button class="tbtn" data-add-in="' + esc(s.section_id) + '">＋ Add task</button></div>';
    });
    var orphans = bySection[null] || [];
    if (orphans.length) out += '<div class="section-row"><span>No section</span></div>' +
      orphans.map(function (t) { return taskRowHtml(t, true); }).join("");
    out += "</div>" +
      '<div class="addtask-row"><button class="tbtn" id="add-section">＋ Add section</button></div>';
    if (!tdata.tasks.length && !meta.sections.length) {
      out = '<div class="empty"><div class="art">📋</div><h3>This project is empty</h3>' +
        "<p>Add a section, then create your first task.</p>" +
        '<button class="tbtn primary" id="add-section">＋ Add section</button></div>';
    }
    return out;
  }

  function boardHtml(meta, tdata) {
    var bySection = {};
    tdata.tasks.forEach(function (t) { (bySection[t.section_id] = bySection[t.section_id] || []).push(t); });
    var cols = meta.sections.map(function (s) {
      var cards = (bySection[s.section_id] || []).map(function (t) {
        return '<div class="card' + (t.completed ? " done" : "") + '" data-task="' + esc(t.task_id) +
          '" draggable="true" data-drag="' + esc(t.task_id) + '">' +
          '<div class="cname">' + esc(t.name) + "</div>" +
          '<div class="cmeta">' +
          (t.priority ? '<span class="chip p-' + esc(t.priority) + '">' + esc(t.priority) + "</span>" : "") +
          (t.due_date ? '<span class="due' + dueClass(t.due_date, t.completed) + '">' + fmtDate(t.due_date) + "</span>" : "") +
          (t.assignee_name ? avatar(t.assignee_name, t.assignee_color, t.assignee_initials, true) : "") +
          "</div></div>";
      }).join("");
      return '<div class="col" data-col="' + esc(s.section_id) + '"><div class="col-head">' + esc(s.name) +
        '<span class="count">' + (bySection[s.section_id] || []).length + "</span></div>" + cards +
        '<button class="addcard" data-add-in="' + esc(s.section_id) + '">＋ Add task</button></div>';
    }).join("");
    return '<div class="board">' + cols +
      '<div class="col" style="background:none"><button class="addcard" id="add-section">＋ Add section</button></div></div>';
  }

  function calendarHtml(tdata) {
    var now = viewProject._calMonth || new Date();
    viewProject._calMonth = now;
    var y = now.getFullYear(), mo = now.getMonth();
    var first = new Date(y, mo, 1);
    var start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7)); // Monday start
    var byDate = {};
    tdata.tasks.forEach(function (t) { if (t.due_date) (byDate[t.due_date] = byDate[t.due_date] || []).push(t); });
    var dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(function (d) {
      return '<div class="cal-dow">' + d + "</div>";
    }).join("");
    var cells = "";
    var today = new Date(); today.setHours(0, 0, 0, 0);
    for (var i = 0; i < 42; i++) {
      var d = new Date(start); d.setDate(start.getDate() + i);
      var iso = d.toISOString().slice(0, 10);
      var items = (byDate[iso] || []).map(function (t) {
        var proj = PROJECTS.find(function (p) { return p.project_id === t.project_id; });
        return '<button class="cal-task" data-task="' + esc(t.task_id) + '" style="background:' +
          esc(proj ? proj.color : "#4573d2") + (t.completed ? ";opacity:.5" : "") + '">' + esc(t.name) + "</button>";
      }).join("");
      cells += '<div class="cal-cell' + (d.getMonth() !== mo ? " other" : "") + '">' +
        '<span class="cal-date' + (d.getTime() === today.getTime() ? " today" : "") + '">' + d.getDate() + "</span>" + items + "</div>";
    }
    var label = now.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    return '<div class="cal-head"><button class="tbtn" id="cal-prev">‹</button>' +
      '<h2>' + label + '</h2><button class="tbtn" id="cal-next">›</button>' +
      '<button class="tbtn" id="cal-today">Today</button></div>' +
      '<div class="cal-grid">' + dows + cells + "</div>";
  }

  function timelineHtml(tdata) {
    var sched = tdata.tasks.filter(function (t) { return t.due_date; });
    var unsched = tdata.tasks.filter(function (t) { return !t.due_date; });
    if (!sched.length) {
      return '<div class="empty"><div class="art">📅</div><h3>Nothing scheduled yet</h3>' +
        "<p>Add due dates to tasks to see them on the timeline.</p></div>";
    }
    var min = null, max = null;
    sched.forEach(function (t) {
      var s = t.start_date || t.due_date, e = t.due_date;
      if (!min || s < min) min = s;
      if (!max || e > max) max = e;
    });
    var start = new Date(min + "T00:00:00"); start.setDate(start.getDate() - 2);
    var end = new Date(max + "T00:00:00"); end.setDate(end.getDate() + 3);
    var days = [];
    for (var d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(new Date(d));
    var DAY_W = 48;
    var header = days.map(function (d) {
      return '<div class="tl-day' + (d.getDay() === 0 || d.getDay() === 6 ? " wknd" : "") + '">' +
        d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + "</div>";
    }).join("");
    var depSet = {};
    tdata.dependencies.forEach(function (dp) { depSet[dp.task_id] = true; });
    var rows = sched.map(function (t) {
      var s = new Date((t.start_date || t.due_date) + "T00:00:00");
      var e = new Date(t.due_date + "T00:00:00");
      var left = Math.round((s - start) / 86400000) * DAY_W;
      var width = (Math.round((e - s) / 86400000) + 1) * DAY_W - 6;
      var proj = PROJECTS.find(function (p) { return p.project_id === t.project_id; });
      return '<div class="tl-row"><button class="tl-bar' + (t.completed ? " done" : "") + '" data-task="' + esc(t.task_id) +
        '" style="left:' + left + "px;width:" + Math.max(width, DAY_W - 6) + "px;background:" +
        esc(proj ? proj.color : "#4573d2") + '">' + (depSet[t.task_id] ? "⛓ " : "") + esc(t.name) + "</button></div>";
    }).join("");
    return '<div class="tl-wrap"><div class="tl-grid" style="width:' + days.length * DAY_W + 'px">' +
      '<div class="tl-days">' + header + "</div>" + rows + "</div></div>" +
      (unsched.length ? '<p class="tl-unscheduled">' + unsched.length + " unscheduled task(s) not shown.</p>" : "");
  }

  function filesHtml(meta, tdata) {
    return '<div class="settings-block"><h3>Import</h3>' +
      "<p class='page-sub'>Upload a CSV with a Name column (optional Notes, Due Date) to add tasks.</p>" +
      '<label class="tbtn">⬆ Import CSV<input type="file" id="import-csv" accept=".csv" hidden></label>' +
      '<p class="form-error" id="import-err" hidden></p><p id="import-ok" class="page-sub"></p></div>' +
      '<div class="settings-block"><h3>Export</h3>' +
      "<p class='page-sub'>Download this project's tasks.</p>" +
      '<a class="tbtn" href="/api/projects/' + esc(meta.project.project_id) + '/export.csv">⬇ Export CSV</a> ' +
      '<a class="tbtn" href="/api/export/workspace.json">⬇ Export workspace JSON</a></div>' +
      '<div class="settings-block"><h3>Rules</h3>' +
      (meta.rules.map(function (r) {
        return '<div class="dep-row">⚙ ' + esc(r.name) + ' <span class="chip">' + (r.enabled ? "On" : "Off") + "</span>" +
          '<button class="tbtn" data-rule="' + esc(r.rule_id) + '" data-en="' + (r.enabled ? 0 : 1) + '">' +
          (r.enabled ? "Turn off" : "Turn on") + "</button></div>";
      }).join("") || "<p class='page-sub'>No rules yet.</p>") +
      '<button class="tbtn" id="add-rule">＋ Add rule</button></div>';
  }

  function projectOverviewHtml(meta) {
    var p = meta.project;
    var members = meta.members.map(function (m) {
      return '<div class="member-row">' + avatar(m.display_name, m.avatar_color, m.initials) +
        '<div class="who">' + esc(m.display_name) + '<div class="em">' + esc(m.access) + "</div></div></div>";
    }).join("");
    return '<div class="settings-block"><h3>Description</h3>' +
      '<textarea class="notes-box" id="ov-desc" placeholder="What is this project about?">' + esc(p.description) + "</textarea></div>" +
      '<div class="settings-block"><h3>Status</h3><div class="toolbar">' +
      [["on_track", "On track"], ["at_risk", "At risk"], ["off_track", "Off track"], ["on_hold", "On hold"], ["complete", "Complete"]].map(function (s) {
        return '<button class="tbtn' + (p.status === s[0] ? " on" : "") + '" data-status="' + s[0] + '">' + s[1] + "</button>";
      }).join("") + "</div>" +
      '<textarea class="notes-box" id="ov-statusnote" placeholder="Status update note…">' + esc(p.status_note) + "</textarea></div>" +
      '<div class="settings-block"><h3>Members</h3>' + members + "</div>";
  }

  function wireProjectBody(meta, tab) {
    var page = document.getElementById("page");
    wireTaskRows(page);
    page.querySelectorAll("[data-add-in]").forEach(function (b) {
      b.onclick = function () { openTaskModal(meta.project.project_id, b.dataset.addIn); };
    });
    var asec = document.getElementById("add-section");
    if (asec) asec.onclick = async function () {
      var name = prompt("Section name");
      if (!name || !name.trim()) return;
      await api("/projects/" + meta.project.project_id + "/sections", { method: "POST", body: { name: name.trim() } });
      route();
    };
    page.querySelectorAll("[data-rename-sec]").forEach(function (b) {
      b.onclick = async function () {
        var name = prompt("Rename section");
        if (!name || !name.trim()) return;
        await api("/sections/" + b.dataset.renameSec, { method: "PATCH", body: { name: name.trim() } });
        route();
      };
    });
    page.querySelectorAll("[data-del-sec]").forEach(function (b) {
      b.onclick = async function () {
        if (!confirm("Delete this section?")) return;
        try { await api("/sections/" + b.dataset.delSec, { method: "DELETE" }); route(); }
        catch (e) { toast(e.message, true); }
      };
    });
    // board drag & drop
    var dragId = null;
    page.querySelectorAll("[data-drag]").forEach(function (c) {
      c.addEventListener("dragstart", function () { dragId = c.dataset.drag; });
    });
    page.querySelectorAll("[data-col]").forEach(function (col) {
      col.addEventListener("dragover", function (ev) { ev.preventDefault(); });
      col.addEventListener("drop", async function (ev) {
        ev.preventDefault();
        if (!dragId) return;
        await api("/tasks/" + dragId, { method: "PATCH", body: { section_id: col.dataset.col } });
        dragId = null; route();
      });
    });
    // calendar nav
    var cp = document.getElementById("cal-prev");
    if (cp) {
      cp.onclick = function () { viewProject._calMonth = shiftMonth(-1); route(); };
      document.getElementById("cal-next").onclick = function () { viewProject._calMonth = shiftMonth(1); route(); };
      document.getElementById("cal-today").onclick = function () { viewProject._calMonth = new Date(); route(); };
    }
    function shiftMonth(n) {
      var m = viewProject._calMonth || new Date();
      return new Date(m.getFullYear(), m.getMonth() + n, 1);
    }
    // overview
    var ov = document.getElementById("ov-desc");
    if (ov) {
      ov.addEventListener("blur", async function () {
        await api("/projects/" + meta.project.project_id, { method: "PATCH", body: { description: ov.value } });
        toast("Description saved");
      });
      page.querySelectorAll("[data-status]").forEach(function (b) {
        b.onclick = async function () {
          await api("/projects/" + meta.project.project_id, { method: "PATCH", body: { status: b.dataset.status } });
          route();
        };
      });
      document.getElementById("ov-statusnote").addEventListener("blur", async function () {
        await api("/projects/" + meta.project.project_id, { method: "PATCH", body: { status_note: this.value } });
        toast("Status note saved");
      });
    }
    // files tab
    var imp = document.getElementById("import-csv");
    if (imp) imp.onchange = async function () {
      if (!this.files.length) return;
      var fd = new FormData(); fd.append("file", this.files[0]);
      var errEl = document.getElementById("import-err");
      errEl.hidden = true;
      try {
        var r = await api("/projects/" + meta.project.project_id + "/import", { method: "POST", body: fd });
        document.getElementById("import-ok").textContent =
          "Imported " + r.imported + " task(s)" + (r.skipped ? ", skipped " + r.skipped + " row(s) without a name." : ".");
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
    var ar = document.getElementById("add-rule");
    if (ar) ar.onclick = async function () {
      var name = prompt("Rule name (e.g. Move completed tasks to Done)");
      if (!name || !name.trim()) return;
      await api("/projects/" + meta.project.project_id + "/rules", {
        method: "POST", body: { name: name.trim(), trigger: "task_completed", action: "move_to_section:Done" } });
      route();
    };
    page.querySelectorAll("[data-rule]").forEach(function (b) {
      b.onclick = async function () {
        await api("/rules/" + b.dataset.rule, { method: "PATCH", body: { enabled: b.dataset.en === "1" } });
        route();
      };
    });
  }

  function openShareModal(meta) {
    var p = meta.project;
    openModal('<h2>Share ' + esc(p.name) + "</h2>" +
      '<div class="field"><label>Who has access</label><select id="sh-mode">' +
      [["workspace", "Workspace members"], ["private", "Private to project members"], ["public_link", "Anyone with the local link"]].map(function (m) {
        return '<option value="' + m[0] + '"' + (p.share_mode === m[0] ? " selected" : "") + ">" + m[1] + "</option>";
      }).join("") + "</select></div>" +
      '<div class="field"><label>Local link</label><input readonly value="' + location.origin + "/app/project/" + esc(p.project_id) + '"></div>' +
      "<p class='page-sub'>Offline demo: links only work on this machine.</p>" +
      '<div class="modal-actions"><button class="tbtn" id="sh-close">Close</button>' +
      '<button class="tbtn primary" id="sh-save">Save</button></div>');
    document.getElementById("sh-close").onclick = closeModal;
    document.getElementById("sh-save").onclick = async function () {
      await api("/projects/" + p.project_id, { method: "PATCH", body: { share_mode: document.getElementById("sh-mode").value } });
      closeModal(); toast("Sharing updated"); route();
    };
  }

  function openProjectMenu(meta) {
    var p = meta.project;
    openModal("<h2>" + esc(p.name) + "</h2>" +
      '<div class="modal-actions" style="justify-content:flex-start;flex-wrap:wrap">' +
      '<button class="tbtn" id="pm-rename">Rename</button>' +
      '<button class="tbtn" id="pm-archive">' + (p.archived ? "Unarchive" : "Archive") + "</button>" +
      '<button class="tbtn danger" id="pm-delete">Delete</button></div>');
    document.getElementById("pm-rename").onclick = async function () {
      var name = prompt("Project name", p.name);
      if (!name || !name.trim()) return;
      await api("/projects/" + p.project_id, { method: "PATCH", body: { name: name.trim() } });
      closeModal(); await loadProjects(); route();
    };
    document.getElementById("pm-archive").onclick = async function () {
      await api("/projects/" + p.project_id, { method: "PATCH", body: { archived: p.archived ? 0 : 1 } });
      closeModal(); await loadProjects(); toast(p.archived ? "Project unarchived" : "Project archived"); route();
    };
    document.getElementById("pm-delete").onclick = async function () {
      if (!confirm("Delete this project? It moves to trash.")) return;
      await api("/projects/" + p.project_id, { method: "DELETE" });
      closeModal(); await loadProjects(); toast("Project moved to trash"); nav("/app/home");
    };
  }

  async function viewSearch(q) {
    loadingPage();
    var data;
    try { data = await api("/search?q=" + encodeURIComponent(q)); } catch (e) { return; }
    var body;
    if (!q) {
      body = '<div class="empty"><div class="art">🔍</div><h3>Search your workspace</h3><p>Find tasks, projects, and people.</p></div>';
    } else if (!data.tasks.length && !data.projects.length && !data.people.length) {
      body = '<div class="empty"><div class="art">🕳</div><h3>No results for “' + esc(q) + '”</h3>' +
        "<p>Try a different keyword or check the spelling.</p></div>";
    } else {
      body = (data.projects.length ? "<h3>Projects</h3><div class='grid-cards'>" + data.projects.map(function (p) {
        return '<div class="gcard" data-navcard="/app/project/' + esc(p.project_id) + '">' +
          '<span class="proj-dot" style="background:' + esc(p.color) + ';display:inline-block"></span> ' + esc(p.name) +
          (p.archived ? ' <span class="chip">Archived</span>' : "") + "</div>";
      }).join("") + "</div>" : "") +
        (data.tasks.length ? "<h3>Tasks</h3><div class='tasklist'>" + data.tasks.map(function (t) { return taskRowHtml(t); }).join("") + "</div>" : "") +
        (data.people.length ? "<h3>People</h3>" + data.people.map(function (u) {
          return '<div class="member-row">' + avatar(u.display_name, u.avatar_color, u.initials) +
            '<div class="who">' + esc(u.display_name) + "</div></div>";
        }).join("") : "");
    }
    setPage("<h1>Search</h1>" + (q ? '<p class="page-sub">Results for “' + esc(q) + '”</p>' : "") + body);
    wireTaskRows(document.getElementById("page"));
    document.querySelectorAll("[data-navcard]").forEach(function (c) {
      c.onclick = function () { nav(c.dataset.navcard); };
    });
  }

  async function viewInbox() {
    loadingPage();
    var archived = viewInbox._archived ? 1 : 0;
    var data;
    try { data = await api("/inbox?archived=" + archived); } catch (e) { return; }
    var items = data.notifications.map(function (n) {
      return '<div class="inbox-item' + (n.read ? "" : " unread") + '">' +
        "<span>" + ({ mention: "💬", comment: "💬", assigned: "👤" }[n.kind] || "🔔") + "</span>" +
        '<div><div>' + esc(n.text) + '</div><div class="when">' + ago(n.created_at) + "</div>" +
        (n.task_id ? '<button class="tbtn" style="margin-top:.3rem" data-opentask="' + esc(n.task_id) + '">Open task</button>' : "") +
        "</div>" +
        '<div class="inbox-actions">' +
        (archived ? '<button class="iconbtn" data-inbox="' + n.notification_id + '/unarchive" title="Restore">↩</button>'
          : '<button class="iconbtn" data-inbox="' + n.notification_id + "/" + (n.read ? "unread" : "read") + '" title="Toggle read">' + (n.read ? "◌" : "●") + "</button>" +
          '<button class="iconbtn" data-inbox="' + n.notification_id + '/archive" title="Archive">🗄</button>') +
        "</div></div>";
    }).join("");
    setPage("<h1>Inbox</h1>" +
      '<div class="tabs"><button class="tab' + (archived ? "" : " active") + '" id="ib-act">Activity</button>' +
      '<button class="tab' + (archived ? " active" : "") + '" id="ib-arch">Archive</button></div>' +
      (items || '<div class="empty"><div class="art">📭</div><h3>' +
        (archived ? "Nothing archived" : "You're all caught up") + "</h3><p>New mentions, assignments, and comments land here.</p></div>"));
    document.getElementById("ib-act").onclick = function () { viewInbox._archived = false; route(); };
    document.getElementById("ib-arch").onclick = function () { viewInbox._archived = true; route(); };
    document.querySelectorAll("[data-inbox]").forEach(function (b) {
      b.onclick = async function () {
        await api("/inbox/" + b.dataset.inbox, { method: "POST" });
        await loadUnread(); route();
      };
    });
    document.querySelectorAll("[data-opentask]").forEach(function (b) {
      b.onclick = function () { openTask(b.dataset.opentask); };
    });
  }

  async function viewPortfolios() {
    loadingPage();
    var data;
    try { data = await api("/portfolios"); } catch (e) { return; }
    var cards = data.portfolios.map(function (pf) {
      return '<div class="gcard" data-navcard="/app/portfolio/' + esc(pf.portfolio_id) + '">' +
        '<span class="proj-icon" style="background:' + esc(pf.color) + '">🗂</span>' +
        "<h3>" + esc(pf.name) + '</h3><div class="gsub">' + pf.project_count + " projects</div></div>";
    }).join("");
    setPage('<div class="page-head"><h1>Portfolios</h1><span class="spacer" style="flex:1"></span>' +
      '<button class="tbtn primary" id="pf-new">＋ New portfolio</button></div>' +
      (cards ? '<div class="grid-cards">' + cards + "</div>"
        : '<div class="empty"><div class="art">🗂</div><h3>No portfolios yet</h3><p>Group projects to monitor progress in one place.</p>' +
        '<button class="tbtn primary" id="pf-new2">＋ New portfolio</button></div>'));
    var n1 = document.getElementById("pf-new"); if (n1) n1.onclick = openPortfolioModal;
    var n2 = document.getElementById("pf-new2"); if (n2) n2.onclick = openPortfolioModal;
    document.querySelectorAll("[data-navcard]").forEach(function (c) {
      c.onclick = function () { nav(c.dataset.navcard); };
    });
  }

  async function viewPortfolio(pfId) {
    loadingPage();
    var data;
    try { data = await api("/portfolios/" + pfId); } catch (e) {
      setPage('<div class="empty"><h3>Portfolio not found</h3></div>'); return;
    }
    var rows = data.projects.map(function (p) {
      var pct = p.task_count ? Math.round(100 * p.done_count / p.task_count) : 0;
      return '<tr style="cursor:pointer" data-navcard="/app/project/' + esc(p.project_id) + '">' +
        '<td><span class="proj-dot" style="background:' + esc(p.color) + ';display:inline-block"></span> ' + esc(p.name) + "</td>" +
        '<td><span class="chip s-' + esc(p.status) + '">' + esc(p.status.replace("_", " ")) + "</span></td>" +
        "<td>" + p.done_count + "/" + p.task_count + ' tasks<div class="progressbar"><div style="width:' + pct + '%"></div></div></td></tr>';
    }).join("");
    setPage('<div class="page-head"><span class="proj-icon" style="background:' + esc(data.portfolio.color) + '">🗂</span>' +
      "<h1>" + esc(data.portfolio.name) + '</h1><span class="spacer" style="flex:1"></span>' +
      '<button class="tbtn primary" id="pf-addproj">＋ Add project</button></div>' +
      (rows ? '<table class="table"><thead><tr><th>Project</th><th>Status</th><th>Progress</th></tr></thead><tbody>' + rows + "</tbody></table>"
        : '<div class="empty"><div class="art">🗂</div><h3>No projects in this portfolio</h3>' +
        '<button class="tbtn primary" id="pf-addproj2">＋ Add project</button></div>'));
    function add() { openProjectModal(pfId); }
    var a1 = document.getElementById("pf-addproj"); if (a1) a1.onclick = add;
    var a2 = document.getElementById("pf-addproj2"); if (a2) a2.onclick = add;
    document.querySelectorAll("[data-navcard]").forEach(function (c) {
      c.onclick = function () { nav(c.dataset.navcard); };
    });
  }

  async function viewGoals() {
    loadingPage();
    var data;
    try { data = await api("/goals"); } catch (e) { return; }
    var rows = data.goals.map(function (g) {
      return '<div class="settings-block"><div class="page-head"><h3 style="margin:0">' + esc(g.name) + "</h3>" +
        '<span class="chip s-' + esc(g.status) + '">' + esc(g.status.replace("_", " ")) + "</span>" +
        '<span class="chip">' + esc(g.time_period) + '</span>' +
        '<span class="spacer" style="flex:1"></span>' + avatar(g.owner_name, g.owner_color, g.owner_initials, true) + "</div>" +
        '<div class="progressbar"><div style="width:' + g.progress + '%"></div></div>' +
        '<div class="toolbar" style="margin-top:.6rem"><span class="page-sub">' + g.progress + "%</span>" +
        '<input type="range" min="0" max="100" value="' + g.progress + '" data-goal="' + esc(g.goal_id) + '" aria-label="Progress">' +
        '<select class="tbtn" data-goalstatus="' + esc(g.goal_id) + '">' +
        [["on_track", "On track"], ["at_risk", "At risk"], ["off_track", "Off track"], ["achieved", "Achieved"]].map(function (s) {
          return '<option value="' + s[0] + '"' + (g.status === s[0] ? " selected" : "") + ">" + s[1] + "</option>";
        }).join("") + "</select></div></div>";
    }).join("");
    setPage('<div class="page-head"><h1>Goals</h1><span class="spacer" style="flex:1"></span>' +
      '<button class="tbtn primary" id="goal-new">＋ New goal</button></div>' +
      (rows || '<div class="empty"><div class="art">🎯</div><h3>No goals yet</h3><p>Connect work to measurable objectives.</p></div>'));
    document.getElementById("goal-new").onclick = openGoalModal;
    document.querySelectorAll("[data-goal]").forEach(function (r) {
      r.onchange = async function () {
        await api("/goals/" + r.dataset.goal, { method: "PATCH", body: { progress: parseInt(r.value, 10) } });
        route();
      };
    });
    document.querySelectorAll("[data-goalstatus]").forEach(function (s) {
      s.onchange = async function () {
        await api("/goals/" + s.dataset.goalstatus, { method: "PATCH", body: { status: s.value } });
        route();
      };
    });
  }

  async function viewActivity() {
    loadingPage();
    var data;
    try { data = await api("/activity"); } catch (e) { return; }
    var items = data.activity.map(function (a) {
      return '<div class="inbox-item"><span>' + avatar(a.display_name, a.avatar_color, a.initials, true) + "</span>" +
        "<div><div><strong>" + esc(a.display_name) + "</strong> " + esc(a.verb) + " " + esc(a.object_type) +
        (a.object_name ? " “" + esc(a.object_name) + "”" : "") + "</div>" +
        '<div class="when">' + ago(a.created_at) + "</div></div></div>";
    }).join("");
    setPage("<h1>Reporting</h1><p class='page-sub'>Workspace activity feed.</p>" +
      (items || '<div class="empty"><div class="art">📈</div><h3>No activity yet</h3></div>'));
  }

  async function viewSettings(tab) {
    loadingPage();
    var u = ME.user;
    var tabs = [["profile", "Profile"], ["notifications", "Notifications"], ["display", "Display"], ["security", "Security"]].map(function (t) {
      return '<button class="tab' + (t[0] === tab ? " active" : "") + '" data-stab="' + t[0] + '">' + t[1] + "</button>";
    }).join("");
    var body = "";
    if (tab === "notifications") {
      body = '<div class="settings-block"><h3>Email-style notifications (local only)</h3>' +
        [["notify_mentions", "Mentions"], ["notify_status", "Status updates"], ["notify_daily_summary", "Daily summary"]].map(function (n) {
          return '<div class="frow"><label style="flex:1">' + n[1] + '</label><input type="checkbox" data-notif="' + n[0] + '"' + (u[n[0]] ? " checked" : "") + "></div>";
        }).join("") + "</div>";
    } else if (tab === "display") {
      body = '<div class="settings-block"><h3>Display</h3>' +
        '<div class="frow"><span class="flabel">Theme</span><select id="set-theme">' +
        ["light", "dark", "system"].map(function (t) { return "<option" + (u.theme === t ? " selected" : "") + ">" + t + "</option>"; }).join("") + "</select></div>" +
        '<div class="frow"><span class="flabel">Default view</span><select id="set-view">' +
        ["list", "board", "calendar"].map(function (v) { return "<option" + (u.task_default_view === v ? " selected" : "") + ">" + v + "</option>"; }).join("") +
        "</select></div><p class='page-sub'>Dark theme is stored but this demo renders light.</p></div>";
    } else if (tab === "security") {
      var sess = await api("/security/sessions");
      body = '<div class="settings-block"><h3>Sessions</h3>' + sess.sessions.map(function (s) {
        return '<div class="dep-row">' + (s.active ? "🟢 Active" : "⚪ Revoked") +
          " · created " + ago(s.created_at) + " · last seen " + ago(s.last_seen_at) + "</div>";
      }).join("") +
        '<button class="tbtn" id="sec-logout-others">Log out other sessions</button></div>' +
        '<div class="settings-block"><h3>Password</h3><p class="page-sub">Use the reset flow on the login screen to change your password.</p>' +
        '<a class="tbtn" href="/-/forgot_password">Reset password</a></div>';
    } else {
      body = '<div class="settings-block"><h3>Profile</h3>' +
        '<div class="field"><label>Full name</label><input id="pr-name" value="' + esc(u.display_name) + '"></div>' +
        '<div class="field"><label>Role</label><input id="pr-role" value="' + esc(u.role_title) + '" placeholder="e.g. Product Manager"></div>' +
        '<div class="field"><label>About me</label><textarea id="pr-about" rows="3">' + esc(u.about_me) + "</textarea></div>" +
        '<div class="field"><label>Avatar color</label>' + colorRow(u.avatar_color) + "</div>" +
        '<div class="modal-actions" style="justify-content:flex-start"><button class="tbtn primary" id="pr-save">Save changes</button></div></div>';
    }
    setPage("<h1>Settings</h1><p class='page-sub'>" + esc(u.email) + '</p><div class="tabs">' + tabs + "</div>" + body);
    document.querySelectorAll("[data-stab]").forEach(function (b) {
      b.onclick = function () { nav("/app/settings?tab=" + b.dataset.stab); };
    });
    var save = document.getElementById("pr-save");
    if (save) {
      wireColorRow(document.getElementById("page"));
      save.onclick = async function () {
        try {
          await api("/profile", { method: "PATCH", body: {
            display_name: document.getElementById("pr-name").value,
            role_title: document.getElementById("pr-role").value,
            about_me: document.getElementById("pr-about").value,
            avatar_color: pickedColor(),
          } });
          await loadMe(); toast("Profile saved"); route();
        } catch (e) { toast(e.message, true); }
      };
    }
    document.querySelectorAll("[data-notif]").forEach(function (cb) {
      cb.onchange = async function () {
        var body = {}; body[cb.dataset.notif] = cb.checked ? 1 : 0;
        await api("/profile", { method: "PATCH", body: body });
        await loadMe(); toast("Preference saved");
      };
    });
    var th = document.getElementById("set-theme");
    if (th) {
      th.onchange = async function () {
        await api("/profile", { method: "PATCH", body: { theme: th.value } });
        await loadMe(); toast("Saved");
      };
      document.getElementById("set-view").onchange = async function () {
        await api("/profile", { method: "PATCH", body: { task_default_view: this.value } });
        await loadMe(); toast("Saved");
      };
    }
    var slo = document.getElementById("sec-logout-others");
    if (slo) slo.onclick = async function () {
      var r = await api("/security/logout-others", { method: "POST" });
      toast("Revoked " + r.revoked + " other session(s)");
      route();
    };
  }

  async function viewAdmin() {
    loadingPage();
    var data;
    try { data = await api("/members"); } catch (e) { return; }
    var isAdmin = ME.role === "admin";
    var rows = data.members.map(function (m) {
      var roleCtl = isAdmin && m.user_id !== ME.user.user_id
        ? '<select class="tbtn" data-role="' + esc(m.user_id) + '">' +
        ["member", "admin"].map(function (r) { return "<option" + (m.role === r ? " selected" : "") + ">" + r + "</option>"; }).join("") + "</select>"
        : '<span class="chip">' + esc(m.role) + "</span>";
      return '<div class="member-row">' + avatar(m.display_name, m.avatar_color, m.initials) +
        '<div class="who">' + esc(m.display_name) + (m.synthetic ? ' <span class="chip">Demo teammate</span>' : "") +
        '<div class="em">' + esc(m.email) + "</div></div>" + roleCtl + "</div>";
    }).join("");
    var invites = data.invites.map(function (i) {
      return '<div class="dep-row">✉ ' + esc(i.email) + ' <span class="chip">' + esc(i.role) + '</span> <span class="chip">' + esc(i.status) + " (local)</span></div>";
    }).join("");
    setPage("<h1>Workspace settings</h1>" +
      '<div class="settings-block"><h3>Workspace name</h3>' +
      '<div class="field"><input id="ws-name" value="' + esc(ME.workspace.name) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
      (isAdmin ? '<button class="tbtn primary" id="ws-save">Save</button>' : '<p class="page-sub">Only admins can rename the workspace.</p>') +
      "</div>" +
      '<div class="settings-block"><h3>Members (' + data.members.length + ")</h3>" + rows + "</div>" +
      '<div class="settings-block"><h3>Invite</h3>' +
      "<p class='page-sub'>Offline demo: invites are recorded locally — no email is sent.</p>" +
      '<div class="toolbar"><input id="inv-email" placeholder="name@example.com" class="tbtn" style="min-width:16rem">' +
      '<select id="inv-role" class="tbtn"><option>member</option><option>admin</option></select>' +
      '<button class="tbtn primary" id="inv-send">Invite</button></div>' +
      '<p class="form-error" id="inv-err" hidden></p>' + invites + "</div>");
    var ws = document.getElementById("ws-save");
    if (ws) ws.onclick = async function () {
      try {
        await api("/workspace", { method: "PATCH", body: { name: document.getElementById("ws-name").value } });
        await loadMe(); toast("Workspace renamed"); route();
      } catch (e) { toast(e.message, true); }
    };
    document.getElementById("inv-send").onclick = async function () {
      var errEl = document.getElementById("inv-err");
      errEl.hidden = true;
      try {
        await api("/invites", { method: "POST", body: {
          email: document.getElementById("inv-email").value,
          role: document.getElementById("inv-role").value } });
        toast("Invite recorded (local simulation)"); route();
      } catch (e) { errEl.textContent = e.message; errEl.hidden = false; }
    };
    document.querySelectorAll("[data-role]").forEach(function (s) {
      s.onchange = async function () {
        try {
          await api("/members/" + s.dataset.role, { method: "PATCH", body: { role: s.value } });
          toast("Role updated"); route();
        } catch (e) { toast(e.message, true); route(); }
      };
    });
  }

  async function viewBilling() {
    loadingPage();
    var data;
    try { data = await api("/billing"); } catch (e) { return; }
    var cards = Object.keys(data.plans).map(function (k) {
      var p = data.plans[k];
      var current = data.plan === k;
      return '<div class="gcard"' + (current ? ' style="border-color:var(--ink)"' : "") + ">" +
        "<h3>" + esc(p.label) + (current ? ' <span class="chip">Current plan</span>' : "") + "</h3>" +
        '<div class="gsub">' + (p.monthly_minor ? "$" + (p.monthly_minor / 100).toFixed(2) + " per user / month" : "Free") + "</div>" +
        (!current && p.monthly_minor ? '<button class="tbtn primary" style="margin-top:.6rem" data-upgrade="' + k + '">Upgrade</button>' : "") +
        "</div>";
    }).join("");
    setPage("<h1>Billing</h1>" +
      "<p class='page-sub'>Offline demo — payments run against the local sandbox adapter (" + esc(data.payment_adapter) + ").</p>" +
      '<div class="grid-cards">' + cards + "</div>" +
      '<div class="settings-block" style="margin-top:1rem"><h3>Sandbox scenario</h3>' +
      '<select id="pay-scenario" class="tbtn">' + data.scenarios.map(function (s) {
        return '<option value="' + esc(s.id) + '">' + esc(s.label) + "</option>";
      }).join("") + "</select><p class='page-sub'>Choose the simulated outcome before clicking Upgrade.</p></div>");
    document.querySelectorAll("[data-upgrade]").forEach(function (b) {
      b.onclick = async function () {
        var scenario = document.getElementById("pay-scenario").value;
        try {
          var r = await api("/billing/upgrade", { method: "POST", body: { plan: b.dataset.upgrade, scenario: scenario } });
          toast("Plan upgraded to " + r.plan + " (simulated)"); await loadMe(); route();
        } catch (e) { toast(e.message || "Simulated payment failed", true); }
      };
    });
  }

  async function viewTrash() {
    loadingPage();
    var data;
    try { data = await api("/trash"); } catch (e) { return; }
    function row(kind, id, name, when) {
      return '<div class="dep-row">🗑 ' + esc(name) + ' <span class="tmeta">' + ago(when) + "</span>" +
        '<span class="spacer" style="flex:1"></span>' +
        '<button class="tbtn" data-restore="' + kind + ":" + esc(id) + '">Restore</button>' +
        '<button class="tbtn danger" data-purge="' + kind + ":" + esc(id) + '">Delete forever</button></div>';
    }
    var items = data.projects.map(function (p) { return row("project", p.project_id, p.name + " (project)", p.deleted_at); })
      .concat(data.tasks.map(function (t) { return row("task", t.task_id, t.name, t.deleted_at); })).join("");
    setPage("<h1>Trash</h1><p class='page-sub'>Deleted items can be restored or removed permanently.</p>" +
      (items || '<div class="empty"><div class="art">🗑</div><h3>Trash is empty</h3></div>'));
    function body(v) {
      var kv = v.split(":");
      return kv[0] === "task" ? { task_id: kv[1] } : { project_id: kv[1] };
    }
    document.querySelectorAll("[data-restore]").forEach(function (b) {
      b.onclick = async function () {
        await api("/trash/restore", { method: "POST", body: body(b.dataset.restore) });
        await loadProjects(); toast("Restored"); route();
      };
    });
    document.querySelectorAll("[data-purge]").forEach(function (b) {
      b.onclick = async function () {
        if (!confirm("Permanently delete? This cannot be undone.")) return;
        await api("/trash/purge", { method: "POST", body: body(b.dataset.purge) });
        toast("Deleted forever"); route();
      };
    });
  }

  function viewHelp() {
    setPage("<h1>Help &amp; getting started</h1>" +
      '<div class="settings-block"><h3>Basics</h3><ul>' +
      "<li><strong>Create</strong> — the ＋ Create button makes tasks, projects, portfolios, goals, and workspaces.</li>" +
      "<li><strong>My tasks</strong> — everything assigned to you, with filters and bulk actions.</li>" +
      "<li><strong>Projects</strong> — switch between List, Board, Calendar, and Timeline tabs.</li>" +
      "<li><strong>Task pane</strong> — click any task to edit fields, subtasks, dependencies, files, and comments.</li>" +
      "<li><strong>Search</strong> — the top bar searches tasks, projects, and people.</li></ul></div>" +
      '<div class="settings-block"><h3>About this demo</h3>' +
      "<p class='page-sub'>This is an offline WebsiteBench clone. All data is stored locally in a" +
      " site-bound SQLite database. Invites and emails are simulated, and payments use a local sandbox." +
      " It is not affiliated with Asana, Inc.</p></div>" +
      '<div class="settings-block"><h3>Support</h3><p class="page-sub">Because this clone runs offline,' +
      ' there is no live support. Check the resources on the <a href="/resources">marketing site</a>.</p></div>');
  }

  function viewNotFound(p) {
    setPage('<div class="empty"><div class="art">🧭</div><h3>Page not found</h3>' +
      "<p>" + esc(p) + ' does not exist. <a data-nav href="/app/home">Go home</a></p></div>');
  }

  // ---------------- boot ----------------
  async function loadMe() {
    ME = await api("/me");
    await loadProjects();
    await loadUnread();
  }
  async function loadProjects() {
    PROJECTS = (await api("/projects")).projects;
    if (document.getElementById("sidebar")) shellRefresh();
  }
  async function loadUnread() {
    UNREAD = (await api("/inbox")).unread;
  }
  function shellRefresh() {
    var page = document.getElementById("page");
    var content = page ? page.innerHTML : "";
    shell(content);
    wireTaskRows(document.getElementById("page"));
  }

  (async function boot() {
    try {
      await loadMe();
    } catch (e) { return; }
    shell("");
    route();
  })();
})();
