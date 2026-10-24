// Health Brief: dark mode, save / mark-read (stored in this browser), search & filters, table sorting.
(function () {
  "use strict";
  var ROOT = document.body.dataset.root || "";
  var PAGE_SIZE = 40;

  // ---------- storage ----------
  function load(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (e) { return fallback; }
  }
  function store(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} }
  var saved = load("hb_saved", {});   // id -> item
  var read = load("hb_read", {});     // id -> timestamp

  // ---------- theme ----------
  document.querySelector(".theme-toggle").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    localStorage.setItem("hb_theme", root.dataset.theme);
  });

  // ---------- cards ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(iso) { var d = new Date(iso); return MONTHS[d.getMonth()] + " " + d.getDate(); }
  var CATS = window.HB_CATS || {};

  // Keep in sync with the card() macro in templates/macros.html.
  function renderCard(i) {
    var data = { id: i.id, title: i.title, link: i.link, source: i.source, published: i.published,
                 category: i.category, score: i.score, summary: i.summary, why: i.why };
    var also = "";
    if (i.also && i.also.length) {
      also = '<details class="also"><summary>Also covered by ' + i.also.length + " more</summary><ul>" +
        i.also.map(function (a) { return '<li><a href="' + esc(a.link) + '" target="_blank" rel="noopener">' + esc(a.source) + "</a></li>"; }).join("") +
        "</ul></details>";
    }
    return '<article class="card" data-id="' + esc(i.id) + '" data-item="' + esc(JSON.stringify(data)) + '">' +
      '<div class="meta"><a class="tag tag-' + esc(i.category) + '" href="' + ROOT + "category/" + esc(i.category) + '.html">' +
      esc((CATS[i.category] || {}).short || i.category) + "</a>" +
      '<span class="score s' + i.score + '" title="Relevance to my profile (1-10)">' + i.score + "</span>" +
      '<span class="src">' + esc(i.source) + '</span><span class="dot">·</span><time datetime="' + esc(i.published) + '">' + fmtDate(i.published) + "</time></div>" +
      '<h3><a href="' + esc(i.link) + '" target="_blank" rel="noopener">' + esc(i.title) + "</a></h3>" +
      (i.summary ? '<p class="summary">' + esc(i.summary) + "</p>" : "") +
      (i.why ? '<p class="why"><span>Why it\'s here</span> ' + esc(i.why) + "</p>" : "") +
      also +
      '<div class="actions"><button type="button" class="btn-save" aria-pressed="false">☆ Save</button>' +
      '<button type="button" class="btn-read" aria-pressed="false">Mark read</button></div></article>';
  }

  function paintCard(card) {
    var id = card.dataset.id;
    var isSaved = !!saved[id], isRead = !!read[id];
    var s = card.querySelector(".btn-save"), r = card.querySelector(".btn-read");
    if (s) { s.setAttribute("aria-pressed", isSaved); s.textContent = isSaved ? "★ Saved" : "☆ Save"; }
    if (r) { r.setAttribute("aria-pressed", isRead); r.textContent = isRead ? "✓ Read" : "Mark read"; }
    card.classList.toggle("is-read", isRead);
  }
  function paintAll(scope) { (scope || document).querySelectorAll(".card").forEach(paintCard); }

  document.addEventListener("click", function (e) {
    var card = e.target.closest(".card");
    if (!card) return;
    var id = card.dataset.id;
    if (e.target.closest(".btn-save")) {
      if (saved[id]) delete saved[id];
      else { try { saved[id] = JSON.parse(card.dataset.item); saved[id].saved_at = Date.now(); } catch (err) { return; } }
      store("hb_saved", saved);
    } else if (e.target.closest(".btn-read")) {
      if (read[id]) delete read[id]; else read[id] = Date.now();
      store("hb_read", read);
    } else if (e.target.closest("h3 a")) {
      read[id] = Date.now();  // opening a story marks it read
      store("hb_read", read);
    } else { return; }
    document.querySelectorAll('.card[data-id="' + id + '"]').forEach(paintCard);
  });
  paintAll();

  // ---------- story browser (All Stories + category pages) ----------
  var browser = document.querySelector(".browser");
  if (browser) {
    var preset = browser.dataset.presetCat;
    var q = browser.querySelector(".q"), period = browser.querySelector(".period"),
        sort = browser.querySelector(".sort"), hideRead = browser.querySelector(".hide-read"),
        list = browser.querySelector(".list"), more = browser.querySelector(".more"),
        count = browser.querySelector(".count");
    var all = [], filtered = [], shown = 0, cat = "";
    var params = new URLSearchParams(location.search);
    if (params.get("q")) q.value = params.get("q");

    browser.querySelectorAll(".chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        cat = chip.dataset.cat;
        browser.querySelectorAll(".chip").forEach(function (c) { c.setAttribute("aria-pressed", c === chip); });
        apply();
      });
    });
    [q, period, sort, hideRead].forEach(function (el) { el.addEventListener("input", apply); });
    more.addEventListener("click", function () { renderMore(); });

    function apply() {
      var terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
      var cutoff = Date.now() - Number(period.value) * 864e5;
      var c = preset || cat;
      filtered = all.filter(function (i) {
        if (c && i.category !== c && (!preset || (i.secondary || []).indexOf(c) < 0)) return false;
        if (new Date(i.published).getTime() < cutoff) return false;
        if (hideRead.checked && read[i.id]) return false;
        if (terms.length) {
          var hay = (i.title + " " + i.summary + " " + i.source + " " + i.why + " " + (i.watch || []).join(" ")).toLowerCase();
          for (var t = 0; t < terms.length; t++) if (hay.indexOf(terms[t]) < 0) return false;
        }
        return true;
      });
      if (sort.value === "date") filtered.sort(function (a, b) { return a.published < b.published ? 1 : -1; });
      else filtered.sort(function (a, b) { return b.score - a.score || (a.published < b.published ? 1 : -1); });
      list.innerHTML = ""; shown = 0;
      count.textContent = filtered.length + (filtered.length === 1 ? " story" : " stories");
      renderMore();
    }
    function renderMore() {
      var next = filtered.slice(shown, shown + PAGE_SIZE);
      var tmp = document.createElement("div");
      tmp.innerHTML = next.map(renderCard).join("");
      paintAll(tmp);
      while (tmp.firstChild) list.appendChild(tmp.firstChild);
      shown += next.length;
      more.hidden = shown >= filtered.length;
      if (!filtered.length) list.innerHTML = '<p class="empty">No stories match.</p>';
    }

    fetch(ROOT + "stories.json").then(function (r) { return r.json(); }).then(function (data) {
      all = data; apply();
    }).catch(function () { list.innerHTML = '<p class="empty">Could not load stories.</p>'; });
  }

  // ---------- saved page ----------
  var savedList = document.querySelector(".saved-list");
  if (savedList) {
    var render = function () {
      var items = Object.keys(saved).map(function (k) { return saved[k]; })
        .sort(function (a, b) { return (b.saved_at || 0) - (a.saved_at || 0); });
      savedList.innerHTML = items.map(renderCard).join("");
      paintAll(savedList);
      document.querySelector(".saved-empty").hidden = items.length > 0;
    };
    render();
    savedList.addEventListener("click", function (e) { if (e.target.closest(".btn-save")) setTimeout(render, 0); });
  }

  // ---------- sortable tables + funding filters ----------
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var ths = table.querySelectorAll("th");
    ths.forEach(function (th, idx) {
      th.addEventListener("click", function () {
        var asc = th.getAttribute("aria-sort") !== "ascending";
        ths.forEach(function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var type = th.dataset.type;
        var rows = Array.prototype.slice.call(table.tBodies[0].rows);
        rows.sort(function (a, b) {
          var x = a.cells[idx], y = b.cells[idx];
          if (!x || !y) return 0;
          var va = x.dataset.sort != null ? x.dataset.sort : x.textContent.trim().toLowerCase();
          var vb = y.dataset.sort != null ? y.dataset.sort : y.textContent.trim().toLowerCase();
          if (type === "num") { va = parseFloat(va) || 0; vb = parseFloat(vb) || 0; }
          return (va < vb ? -1 : va > vb ? 1 : 0) * (asc ? 1 : -1);
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
  });
  var tf = document.querySelector(".table-filter"), co = document.querySelector(".consumer-only");
  if (tf) {
    var filterRows = function () {
      var t = tf.value.toLowerCase();
      document.querySelectorAll("table.funding tbody tr").forEach(function (tr) {
        var ok = (!t || tr.textContent.toLowerCase().indexOf(t) >= 0) &&
                 (!co.checked || Number(tr.dataset.score) >= 5);
        tr.hidden = !ok;
      });
    };
    tf.addEventListener("input", filterRows);
    co.addEventListener("change", filterRows);
  }
})();
