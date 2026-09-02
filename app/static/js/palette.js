/* PersonalOS — command palette.
 *
 * Three modes inferred from the input (UI_DESIGN_SYSTEM.md §5):
 *   plain text  search across records
 *   > prefix    commands
 *   @ prefix    people
 *   # prefix    tags
 *
 * The index comes from /shell/palette.json, which every later phase extends
 * with its own records — the palette itself never learns about modules.
 */
(function () {
  "use strict";

  var PersonalOS = (window.PersonalOS = window.PersonalOS || {});

  var MAX_RESULTS = 40;

  var input = document.getElementById("pos-palette-input");
  var list = document.getElementById("pos-palette-results");
  var panel = document.getElementById("pos-palette");
  if (!input || !list || !panel) return;

  var catalog = { navigation: [], commands: [], entries: [] };
  var visible = [];
  var active = 0;

  PersonalOS.index.then(function (index) {
    catalog = index;
    if (panel.open) render(input.value);
  });

  /* --- matching -----------------------------------------------------------
   * Subsequence match, so "acsl" finds "Acme Sell Side". Scored so that a
   * prefix match on the label always outranks a scattered one.
   */
  function score(text, query) {
    if (!query) return 1;
    var haystack = text.toLowerCase();
    var needle = query.toLowerCase();

    var direct = haystack.indexOf(needle);
    if (direct === 0) return 1000;
    if (direct > 0) return 500 - direct;

    var position = 0;
    for (var i = 0; i < needle.length; i++) {
      position = haystack.indexOf(needle[i], position);
      if (position === -1) return 0;
      position++;
    }
    return 100 - position;
  }

  function pool(mode) {
    if (mode === ">") return catalog.commands.concat(catalog.navigation);
    if (mode === "@") return catalog.entries.filter(function (e) { return e.type === "person"; });
    if (mode === "#") return catalog.entries.filter(function (e) { return e.type === "tag"; });
    return catalog.entries.concat(catalog.navigation);
  }

  function search(raw) {
    var mode = "";
    var query = raw.trim();
    if (query[0] === ">" || query[0] === "@" || query[0] === "#") {
      mode = query[0];
      query = query.slice(1).trim();
    }

    return pool(mode)
      .map(function (item) {
        return { item: item, score: score(item.label + " " + (item.group || ""), query) };
      })
      .filter(function (scored) { return scored.score > 0; })
      .sort(function (a, b) { return b.score - a.score; })
      .slice(0, MAX_RESULTS)
      .map(function (scored) { return scored.item; });
  }

  /* --- rendering ---------------------------------------------------------- */

  function render(raw) {
    visible = search(raw);
    active = 0;
    list.innerHTML = "";

    if (!visible.length) {
      var empty = document.createElement("li");
      empty.className = "pos-palette-empty";
      empty.textContent = raw.trim()
        ? "Nothing matches “" + raw.trim() + "”."
        : "Start typing, or press > for commands.";
      list.appendChild(empty);
      return;
    }

    var lastGroup = null;
    visible.forEach(function (item, position) {
      var group = item.group || (item.type === "command" ? "Commands" : "Go to");
      if (group !== lastGroup) {
        var heading = document.createElement("li");
        heading.className = "pos-palette-group";
        heading.setAttribute("aria-hidden", "true");
        heading.textContent = group;
        list.appendChild(heading);
        lastGroup = group;
      }

      var row = document.createElement("li");
      row.className = "pos-palette-item" + (position === active ? " is-active" : "");
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", position === active ? "true" : "false");
      row.dataset.position = String(position);

      var label = document.createElement("span");
      label.className = "pos-palette-item-label";
      label.textContent = item.label;
      row.appendChild(label);

      if (item.badge) {
        var badge = document.createElement("span");
        badge.className = "pos-badge pos-badge-neutral";
        badge.textContent = item.badge;
        row.appendChild(badge);
      }

      row.addEventListener("click", function () { open(item); });
      list.appendChild(row);
    });
  }

  function highlight(next) {
    if (!visible.length) return;
    active = (next + visible.length) % visible.length;
    var items = list.querySelectorAll(".pos-palette-item");
    items.forEach(function (element) {
      var isActive = Number(element.dataset.position) === active;
      element.classList.toggle("is-active", isActive);
      element.setAttribute("aria-selected", isActive ? "true" : "false");
      if (isActive) element.scrollIntoView({ block: "nearest" });
    });
  }

  function open(item, newTab) {
    if (!item || !item.url) return;
    panel.close();
    if (newTab) {
      window.open(item.url, "_blank", "noopener");
    } else {
      window.location.href = item.url;
    }
  }

  /* --- binding ------------------------------------------------------------ */

  input.addEventListener("input", function () { render(input.value); });

  input.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown") { event.preventDefault(); highlight(active + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); highlight(active - 1); }
    else if (event.key === "Enter") {
      event.preventDefault();
      open(visible[active], event.ctrlKey || event.metaKey);
    }
  });

  // The dialog is inside a <form method="dialog">; without this the palette
  // would submit and close on the first Enter regardless of selection.
  panel.addEventListener("submit", function (event) { event.preventDefault(); });
})();
