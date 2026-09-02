/* PersonalOS — shell behaviour and the hotkey registry.
 *
 * HOTKEYS below is the single source of truth: it both binds the keys and
 * generates the `?` overlay, so the documentation cannot drift from the
 * behaviour (UI_DESIGN_SYSTEM.md §5).
 *
 * Vanilla only. No build step, no framework, no inline script.
 */
(function () {
  "use strict";

  var PersonalOS = (window.PersonalOS = window.PersonalOS || {});

  /* --- shared palette index ---------------------------------------------
   * Fetched once and reused by the palette and the g-prefix keys, so a
   * "go to" hotkey can never land on a module that is switched off.
   */
  PersonalOS.index = fetch("/shell/palette.json", { credentials: "same-origin" })
    .then(function (response) {
      if (!response.ok) throw new Error("palette index unavailable");
      return response.json();
    })
    .catch(function () {
      return { navigation: [], commands: [], entries: [], goto: {} };
    });

  function dialog(id) {
    var element = document.getElementById(id);
    return element && typeof element.showModal === "function" ? element : null;
  }

  function openDialog(id) {
    var element = dialog(id);
    if (!element) return false;
    if (!element.open) element.showModal();
    return true;
  }

  PersonalOS.openPalette = function () {
    if (!openDialog("pos-palette")) return;
    var input = document.getElementById("pos-palette-input");
    if (input) {
      input.value = "";
      input.dispatchEvent(new Event("input"));
      input.focus();
    }
  };

  PersonalOS.openHotkeys = function () {
    openDialog("pos-hotkeys");
  };

  /* --- helpers ----------------------------------------------------------- */

  function isTypingTarget(element) {
    if (!element) return false;
    if (element.isContentEditable) return true;
    var tag = element.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  }

  function clickIfPresent(selector) {
    var element = document.querySelector(selector);
    if (element) {
      element.click();
      return true;
    }
    return false;
  }

  function focusSearch() {
    var field =
      document.querySelector('[role="search"] input') ||
      document.querySelector('input[type="search"]');
    if (field) {
      field.focus();
      field.select();
      return true;
    }
    PersonalOS.openPalette();
    return true;
  }

  function goTo(letter) {
    PersonalOS.index.then(function (index) {
      var url = index.goto && index.goto[letter];
      if (url) window.location.href = url;
    });
  }

  /* --- list navigation ---------------------------------------------------
   * j / k / x / Enter operate on whichever table declares itself navigable.
   */

  function rows() {
    var table = document.querySelector("[data-pos-table] tbody");
    return table ? Array.prototype.slice.call(table.rows) : [];
  }

  var cursor = -1;

  function moveCursor(delta) {
    var all = rows();
    if (!all.length) return;
    if (cursor >= 0 && all[cursor]) all[cursor].classList.remove("is-cursor");
    cursor = Math.max(0, Math.min(all.length - 1, cursor + delta));
    var row = all[cursor];
    row.classList.add("is-cursor");
    row.scrollIntoView({ block: "nearest" });
    var link = row.querySelector("a");
    if (link) link.focus();
  }

  function openCursorRow() {
    var all = rows();
    if (cursor < 0 || !all[cursor]) return;
    var link = all[cursor].querySelector("a");
    if (link) link.click();
  }

  function toggleCursorRow() {
    var all = rows();
    if (cursor < 0 || !all[cursor]) return;
    var box = all[cursor].querySelector('input[type="checkbox"]');
    if (box) box.click();
  }

  /* --- the registry ------------------------------------------------------ */

  var HOTKEYS = [
    { label: "Ctrl K", description: "Command palette", match: function (e) { return (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k"; }, run: function () { PersonalOS.openPalette(); }, whileTyping: true },
    { label: "?", description: "This list of shortcuts", match: function (e) { return e.key === "?"; }, run: function () { PersonalOS.openHotkeys(); } },
    { label: "/", description: "Focus the search box on this page", match: function (e) { return e.key === "/"; }, run: focusSearch },
    { label: "n", description: "New record in the current context", match: function (e) { return e.key === "n"; }, run: function () { clickIfPresent("[data-pos-new]"); } },
    { label: "e", description: "Edit the current record", match: function (e) { return e.key === "e"; }, run: function () { clickIfPresent("[data-pos-edit]"); } },
    // Bound to an explicit marker, not to any submit button on the page — "s"
    // must never fire a filter form the user was only reading.
    { label: "s", description: "Save the open form", match: function (e) { return e.key === "s" && !e.ctrlKey && !e.metaKey; }, run: function () { clickIfPresent("[data-pos-save]"); } },
    { label: "j", description: "Move down a list", match: function (e) { return e.key === "j"; }, run: function () { moveCursor(1); } },
    { label: "k", description: "Move up a list", match: function (e) { return e.key === "k"; }, run: function () { moveCursor(-1); } },
    { label: "x", description: "Toggle selection on the focused row", match: function (e) { return e.key === "x"; }, run: toggleCursorRow },
    { label: "Enter", description: "Open the focused row", match: function (e) { return e.key === "Enter" && cursor >= 0; }, run: openCursorRow },
    { label: "Esc", description: "Close the palette, a drawer or a dialog", match: function (e) { return e.key === "Escape"; }, run: closeTopDialog, whileTyping: true },
    { label: "g then c", description: "Go to Command Center", sequence: "c" },
    { label: "g then p", description: "Go to Projects", sequence: "p" },
    { label: "g then s", description: "Go to Staffing Board", sequence: "s" },
    { label: "g then t", description: "Go to Tasks", sequence: "t" },
    { label: "g then n", description: "Go to Notes Vault", sequence: "n" },
    { label: "g then a", description: "Go to Activity Log", sequence: "a" }
  ];

  PersonalOS.hotkeys = HOTKEYS;

  function closeTopDialog() {
    var open = document.querySelector("dialog[open]");
    if (open) {
      open.close();
      return;
    }
    var menu = document.querySelector("details.pos-menu[open]");
    if (menu) menu.open = false;
  }

  /* --- binding ----------------------------------------------------------- */

  var awaitingGoTo = false;
  var goToTimer = null;

  function cancelGoTo() {
    awaitingGoTo = false;
    if (goToTimer) window.clearTimeout(goToTimer);
    goToTimer = null;
  }

  document.addEventListener("keydown", function (event) {
    var typing = isTypingTarget(event.target);

    if (awaitingGoTo && !typing) {
      var letter = event.key.toLowerCase();
      cancelGoTo();
      var known = HOTKEYS.some(function (entry) { return entry.sequence === letter; });
      if (known) {
        event.preventDefault();
        goTo(letter);
        return;
      }
    }

    if (!typing && event.key === "g" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      awaitingGoTo = true;
      goToTimer = window.setTimeout(cancelGoTo, 1500);
      return;
    }

    for (var i = 0; i < HOTKEYS.length; i++) {
      var entry = HOTKEYS[i];
      if (!entry.match) continue;
      if (typing && !entry.whileTyping) continue;
      if (entry.match(event)) {
        event.preventDefault();
        entry.run();
        return;
      }
    }
  });

  /* --- the ? overlay, generated from the same registry -------------------- */

  function renderHotkeyTable() {
    var body = document.getElementById("pos-hotkey-rows");
    if (!body) return;
    body.innerHTML = "";
    HOTKEYS.forEach(function (entry) {
      var row = document.createElement("tr");

      var keyCell = document.createElement("td");
      entry.label.split(" ").forEach(function (part, position) {
        if (part === "then") {
          keyCell.appendChild(document.createTextNode(" then "));
          return;
        }
        var kbd = document.createElement("kbd");
        kbd.className = "pos-kbd";
        kbd.textContent = part;
        keyCell.appendChild(kbd);
        if (position === 0 && entry.label.indexOf("then") === -1) {
          keyCell.appendChild(document.createTextNode(" "));
        }
      });

      var descriptionCell = document.createElement("td");
      descriptionCell.textContent = entry.description;

      row.appendChild(keyCell);
      row.appendChild(descriptionCell);
      body.appendChild(row);
    });
  }

  /* --- chrome ------------------------------------------------------------- */

  function bindChrome() {
    var searchButton = document.getElementById("pos-search-open");
    if (searchButton) {
      searchButton.addEventListener("click", PersonalOS.openPalette);
    }

    document.querySelectorAll("[data-pos-open]").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        var target = trigger.getAttribute("data-pos-open");
        if (target === "palette") PersonalOS.openPalette();
        if (target === "hotkeys") PersonalOS.openHotkeys();
      });
    });

    var toggle = document.getElementById("pos-sidebar-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        var collapsed = document.body.classList.toggle("pos-rail");
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        var body = new FormData();
        body.append("collapsed", collapsed ? "1" : "0");
        fetch("/shell/sidebar", { method: "POST", body: body, credentials: "same-origin" })
          .catch(function () { /* the class is already applied; persistence is a nicety */ });
      });
    }

    document.querySelectorAll(".pos-flash-close").forEach(function (button) {
      button.addEventListener("click", function () {
        var flash = button.closest(".pos-flash");
        if (flash) flash.remove();
      });
    });

    // A details menu left open swallows the next click elsewhere on the page.
    document.addEventListener("click", function (event) {
      document.querySelectorAll("details.pos-menu[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) menu.open = false;
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderHotkeyTable();
    bindChrome();
  });
})();
