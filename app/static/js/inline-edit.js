/* PersonalOS — inline table editing.
 *
 * Any <td data-field="..."> inside a <table data-edit-base="..."> becomes a
 * click-to-edit cell. Each field saves independently on commit (Enter, Tab,
 * or blur) via a POST to the table's edit-base with {id} substituted from
 * the row's data-record-id. See docs/superpowers/specs/2026-09-02-inline-table-editing-design.md.
 */
(function () {
  "use strict";

  function optionsFromSrc(selector) {
    var el = document.querySelector(selector);
    if (!el) return [];
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return [];
    }
  }

  function buildInput(td) {
    var type = td.dataset.type;
    var currentValue = td.dataset.value !== undefined ? td.dataset.value : td.textContent.trim();
    var input;

    if (type === "select" || type === "fk-select") {
      input = document.createElement("select");
      // A blank option only makes sense for nullable columns: every
      // fk-select (an unset person link is normal) or a plain select that
      // explicitly opts in with data-nullable="1". Every other plain
      // select backs a NOT NULL / CHECK-constrained column, so offering a
      // blank there only produces a save error rather than a real choice.
      if (type === "fk-select" || td.dataset.nullable === "1") {
        var blank = document.createElement("option");
        blank.value = "";
        blank.textContent = "—";
        input.appendChild(blank);
      }

      var opts;
      if (type === "select") {
        opts = (td.dataset.options || "")
          .split(",")
          .filter(function (o) { return o !== ""; })
          .map(function (o) { return { id: o, label: o }; });
      } else {
        opts = optionsFromSrc(td.dataset.optionsSrc);
      }
      opts.forEach(function (o) {
        var opt = document.createElement("option");
        opt.value = String(o.id);
        opt.textContent = o.label;
        // For plain selects, match case-insensitively against display text.
        // For fk-selects, match case-sensitively against data-value id.
        var shouldSelect = type === "select"
          ? String(o.id).toLowerCase() === String(currentValue).toLowerCase()
          : String(o.id) === String(currentValue);
        if (shouldSelect) opt.selected = true;
        input.appendChild(opt);
      });
    } else {
      input = document.createElement("input");
      input.type = type === "number" ? "number" : type === "date" ? "date" : "text";
      input.value = currentValue || "";
    }
    input.className = "pos-inline-input";
    return input;
  }

  function endpointFor(td) {
    var tr = td.closest("tr");
    var table = td.closest("table");
    var base = (table && table.dataset.editBase) || "";
    var url = base.replace("{id}", tr.dataset.recordId);
    // A few sub-resource routes (e.g. Work Resources) nest under their
    // parent's id too — data-project-id can be set on the <tr> (overrides)
    // or the <table> (shared for every row) when a route needs it.
    var projectId = tr.dataset.projectId || (table && table.dataset.projectId);
    if (projectId) url = url.replace("{project_id}", projectId);
    return url;
  }

  function clearError(td) {
    td.classList.remove("pos-inline-error");
    var note = td.querySelector(".pos-inline-error-msg");
    if (note) note.remove();
  }

  function showError(td, message) {
    td.classList.add("pos-inline-error");
    var note = td.querySelector(".pos-inline-error-msg");
    if (!note) {
      note = document.createElement("div");
      note.className = "pos-inline-error-msg";
      td.appendChild(note);
    }
    note.textContent = message;
  }

  function enterEdit(td) {
    if (td.dataset.editing === "1") return;
    var tr = td.closest("tr");
    if (!tr || tr.dataset.archived === "1") return;
    if (!td.dataset.field) return;

    td.dataset.editing = "1";
    td.dataset.savedHtml = td.innerHTML;
    clearError(td);

    var input = buildInput(td);
    td.textContent = "";
    td.appendChild(input);
    input.focus();
    if (typeof input.select === "function") input.select();

    var settled = false;

    function commit() {
      if (settled || td.dataset.editing !== "1") return;
      settled = true;
      var newValue = input.value;
      var endpoint = endpointFor(td);
      td.classList.add("pos-inline-busy");

      var body = new URLSearchParams();
      body.set("field", td.dataset.field);
      body.set("value", newValue);

      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          td.classList.remove("pos-inline-busy");
          if (data && data.ok) {
            td.dataset.editing = "0";
            td.dataset.value = newValue;
            td.textContent = data.display;
            clearError(td);
          } else {
            settled = false;
            showError(td, (data && data.error) || "Save failed.");
            input.focus();
          }
        })
        .catch(function () {
          td.classList.remove("pos-inline-busy");
          settled = false;
          showError(td, "Could not reach the server.");
          input.focus();
        });
    }

    function cancel() {
      settled = true;
      td.dataset.editing = "0";
      clearError(td);
      // Restore via innerHTML, not textContent: the saved value is the
      // server's own Jinja-escaped markup (a badge or link) as the browser
      // already rendered it once, not fresh unescaped input, so re-parsing
      // it back into the DOM is safe. textContent would flatten a badge or
      // link to plain text even though nothing was actually edited.
      td.innerHTML = td.dataset.savedHtml;
    }

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        commit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        // Only cancel if no commit is already in flight. Once settled=true,
        // the fetch is in progress and the server's response owns the cell.
        if (!settled) cancel();
      }
      // Tab is left to the browser's default focus movement; blur (below)
      // performs the commit before focus actually leaves the input.
    });
    input.addEventListener("blur", function () {
      if (td.dataset.editing === "1") commit();
    });
  }

  document.addEventListener("click", function (event) {
    // A cell that renders its value as a link (e.g. a person's name) should
    // still navigate on click; only the rest of the cell enters edit mode.
    if (event.target.closest("a")) return;
    var td = event.target.closest("td[data-field]");
    if (!td || td.dataset.editing === "1") return;
    enterEdit(td);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
    if (event.target.closest("a")) return;
    var td = event.target.closest("td[data-field]");
    if (!td || td !== event.target || td.dataset.editing === "1") return;
    event.preventDefault();
    enterEdit(td);
  });
})();
