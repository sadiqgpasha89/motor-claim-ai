/*
 * Chapter pager: shows one ".page" at a time and keeps every existing "#section-id" link working.
 * A hash may name a page ("#page-trust") or any element inside one ("#agent-ops"); either way the
 * containing page is shown and the target is scrolled into view. Loaded before the other site scripts
 * so that hidden pages carry the ".hidden" class when app.js renders Mermaid diagrams on load.
 */
(function () {
  "use strict";

  var pages = Array.prototype.slice.call(document.querySelectorAll(".page"));
  if (!pages.length) return;
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".chapter-tabs a[data-page]"));
  var baseTitle = "MotorClaim AI";
  var current = null;

  function pageFor(node) {
    if (!node) return null;
    if (node.classList && node.classList.contains("page")) return node;
    return node.closest ? node.closest(".page") : null;
  }

  function renderDiagrams(page) {
    if (!window.mermaid || !window.mermaid.run) return;
    var nodes = Array.prototype.slice
      .call(page.querySelectorAll(".mermaid:not([data-processed='true'])"))
      .filter(function (n) {
        return !n.closest(".hidden");
      });
    if (nodes.length) {
      try {
        window.mermaid.run({ nodes: nodes });
      } catch (e) {
        /* diagrams are decorative; never break navigation */
      }
    }
  }

  function show(page) {
    if (page === current) return false;
    pages.forEach(function (p) {
      var on = p === page;
      p.classList.toggle("hidden", !on);
      if (on) p.removeAttribute("aria-hidden");
      else p.setAttribute("aria-hidden", "true");
    });
    tabs.forEach(function (t) {
      var on = t.getAttribute("data-page") === page.id;
      t.classList.toggle("active", on);
      if (on) {
        t.setAttribute("aria-current", "page");
        if (t.scrollIntoView && t.parentNode.scrollWidth > t.parentNode.clientWidth) {
          t.parentNode.scrollLeft = t.offsetLeft - 16;
        }
      } else {
        t.removeAttribute("aria-current");
      }
    });
    var label = page.getAttribute("data-title");
    document.title = label && page.id !== "page-start" ? label + " · " + baseTitle : baseTitle + " — Faster, governed motor claims: AI agents do the work, people keep control";
    current = page;
    if (document.readyState !== "loading") renderDiagrams(page);
    return true;
  }

  function reveal(id, smooth) {
    var target = id ? document.getElementById(id) : null;
    var page = pageFor(target);
    if (!page) return false;
    var switched = show(page);
    if (target === page) {
      window.scrollTo({ top: 0, behavior: "instant" });
    } else {
      target.scrollIntoView({ behavior: smooth && !switched ? "smooth" : "instant", block: "start" });
    }
    return true;
  }

  function route() {
    var id = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    if (!reveal(id, false)) {
      show(pages[0]);
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a) return;
    var id = decodeURIComponent(a.getAttribute("href").slice(1));
    if (!id || !pageFor(document.getElementById(id))) return;
    e.preventDefault();
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    reveal(id, true);
  });

  function realignDeepLink() {
    var id = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    var target = id ? document.getElementById(id) : null;
    if (target && pageFor(target) !== target && pageFor(target) === current) {
      target.scrollIntoView({ behavior: "instant", block: "start" });
    }
  }

  window.addEventListener("load", realignDeepLink);
  window.addEventListener("popstate", route);
  window.addEventListener("hashchange", route);

  document.addEventListener("DOMContentLoaded", function () {
    // Our handler is registered before app.js's, so wait a tick for it to initialise Mermaid.
    // The other scripts render content above deep-linked sections, so re-align once they're done.
    setTimeout(function () {
      if (current) renderDiagrams(current);
      realignDeepLink();
    }, 0);

    var filter = document.getElementById("gloss-filter");
    if (filter) {
      filter.addEventListener("input", function () {
        var q = filter.value.trim().toLowerCase();
        var shown = 0;
        document.querySelectorAll(".gloss-list > div").forEach(function (row) {
          var hit = !q || row.textContent.toLowerCase().indexOf(q) !== -1;
          row.classList.toggle("hidden", !hit);
          if (hit) shown += 1;
        });
        document.querySelectorAll(".gloss-list").forEach(function (list) {
          var any = list.querySelector(":scope > div:not(.hidden)");
          list.classList.toggle("hidden", !any);
          var h = list.previousElementSibling;
          if (h && h.classList.contains("gloss-group")) h.classList.toggle("hidden", !any);
        });
        var empty = document.getElementById("gloss-empty");
        if (empty) empty.classList.toggle("hidden", shown > 0);
      });
    }
  });

  window.MCPager = { reveal: reveal };
  route();
})();
