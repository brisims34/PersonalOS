/* PersonalOS — table sort, filter and export.
 *
 * Applies to any table marked `data-pos-table`. Sorting is client-side and
 * therefore only ever reorders the rows already on the page; paginated views
 * sort on the server so the ordering is over the whole result set, not the
 * current page. Export writes the visible rows to CSV.
 */
(function () {
  "use strict";

  function cellText(row, column) {
    var cell = row.cells[column];
    return cell ? cell.textContent.trim() : "";
  }

  /* Accounting formatting has to be undone before comparing: "(1,234.56)" is
   * negative, "$1,234" carries a symbol, and "62%" is a number. */
  function asNumber(text) {
    var cleaned = text.replace(/[$,%\s]/g, "");
    var negative = /^\(.*\)$/.test(cleaned);
    if (negative) cleaned = cleaned.slice(1, -1);
    if (cleaned === "" || isNaN(Number(cleaned))) return null;
    return negative ? -Number(cleaned) : Number(cleaned);
  }

  function compare(a, b) {
    var numberA = asNumber(a);
    var numberB = asNumber(b);
    if (numberA !== null && numberB !== null) return numberA - numberB;
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }

  function makeSortable(table) {
    var head = table.tHead;
    var body = table.tBodies[0];
    if (!head || !body) return;

    Array.prototype.forEach.call(head.rows[0].cells, function (header, column) {
      header.setAttribute("aria-sort", "none");
      header.tabIndex = 0;

      function sort() {
        var current = header.getAttribute("aria-sort");
        var ascending = current !== "ascending";

        Array.prototype.forEach.call(head.rows[0].cells, function (other) {
          other.setAttribute("aria-sort", "none");
        });
        header.setAttribute("aria-sort", ascending ? "ascending" : "descending");

        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (rowA, rowB) {
          var result = compare(cellText(rowA, column), cellText(rowB, column));
          return ascending ? result : -result;
        });
        rows.forEach(function (row) { body.appendChild(row); });
      }

      header.addEventListener("click", sort);
      header.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });
  }

  function toCsv(table) {
    var lines = [];
    Array.prototype.forEach.call(table.rows, function (row) {
      if (row.hidden) return;
      var fields = Array.prototype.map.call(row.cells, function (cell) {
        return '"' + cell.textContent.trim().replace(/"/g, '""') + '"';
      });
      lines.push(fields.join(","));
    });
    return lines.join("\r\n");
  }

  function makeExportable(table) {
    var button = document.querySelector('[data-pos-export="' + table.id + '"]');
    if (!button) return;
    button.addEventListener("click", function () {
      var blob = new Blob([toCsv(table)], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = (table.dataset.posExportName || "personalos") + ".csv";
      link.click();
      URL.revokeObjectURL(url);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-pos-table]").forEach(function (table) {
      /* A server-sorted table is ordered over the whole result set. Re-sorting
       * the rendered page on top of that would reorder one page of many while
       * appearing to have sorted everything. */
      if (table.classList.contains("pos-table-sortable")
          && !table.hasAttribute("data-pos-server-sort")) {
        makeSortable(table);
      }
      makeExportable(table);
    });

    /* One filter menu open at a time; Escape closes them. */
    document.addEventListener("click", function (event) {
      document.querySelectorAll("details.pos-th-filter[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) menu.removeAttribute("open");
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll("details.pos-th-filter[open]").forEach(function (menu) {
        menu.removeAttribute("open");
      });
    });

    /* The CSP forbids inline handlers, so submit-on-change is wired here.
     * The <noscript> button beside each control is the fallback. */
    document.querySelectorAll("[data-pos-submit-on-change]").forEach(function (control) {
      control.addEventListener("change", function () {
        if (control.form) control.form.submit();
      });
    });
  });
})();
