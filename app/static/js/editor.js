/* PersonalOS — markdown editor.
 *
 * The preview is rendered by the server, not in the browser. One renderer for
 * preview and read view means what you see while typing cannot diverge from
 * what gets saved — and it keeps the sanitiser on the server side, which is
 * the only side that can be trusted.
 */
(function () {
  "use strict";

  var input = document.getElementById("body");
  var preview = document.getElementById("pos-preview");
  if (!input || !preview) return;

  var timer = null;
  var lastRendered = null;

  function renderPreview() {
    var body = input.value;
    if (body === lastRendered) return;
    lastRendered = body;

    var payload = new FormData();
    payload.append("body", body);

    fetch("/notes/preview", { method: "POST", body: payload, credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (data) { preview.innerHTML = data.html; })
      .catch(function () {
        preview.textContent = "Preview unavailable — the note itself is unaffected.";
      });
  }

  input.addEventListener("input", function () {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(renderPreview, 350);
  });

  // Tab inserts two spaces rather than leaving the field: a markdown editor
  // where you cannot indent a list is not an editor.
  input.addEventListener("keydown", function (event) {
    if (event.key !== "Tab" || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    var start = input.selectionStart;
    var end = input.selectionEnd;
    input.value = input.value.slice(0, start) + "  " + input.value.slice(end);
    input.selectionStart = input.selectionEnd = start + 2;
  });

  // Ctrl-S saves, because everybody presses it.
  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      var form = document.getElementById("pos-note-form");
      if (form) form.submit();
    }
  });

  renderPreview();
})();
