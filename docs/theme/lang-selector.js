// Language selector for Remote Claude docs
//
// URL layout:
//   /           -> English (default)
//   /en/...     -> English (explicit)
//   /zh/...     -> Chinese
//
// The selector shows  EN | ZH  in the top-right menu bar.
// Clicking switches to the same page in the other language.
(function () {
  "use strict";

  var path = window.location.pathname;

  // ── Detect current language from URL ──
  var currentLang = "en"; // default
  if (path.match(/\/zh(\/|$)/)) {
    currentLang = "zh";
  }

  // ── Compute the equivalent page path in the target language ──
  function switchLangPath(targetLang) {
    var pagePath; // the part after the language prefix

    if (currentLang === "zh") {
      // Strip /zh/ prefix (or /zh at end)
      pagePath = path.replace(/^\/zh\/?/, "/");
    } else if (path.match(/^\/en\//)) {
      // Strip /en/ prefix
      pagePath = path.replace(/^\/en\/?/, "/");
    } else {
      // Root English: path is already the page path
      pagePath = path;
    }

    // Ensure pagePath starts with /
    if (pagePath.charAt(0) !== "/") pagePath = "/" + pagePath;

    if (targetLang === "zh") {
      return "/zh" + pagePath;
    } else {
      // English: go to root (default)
      return pagePath;
    }
  }

  // ── Build the selector DOM ──
  var container = document.createElement("span");
  container.className = "lang-selectors";

  var langs = [
    { label: "EN", value: "en" },
    { label: "ZH", value: "zh" },
  ];

  langs.forEach(function (lang, i) {
    if (i > 0) {
      var sep = document.createElement("span");
      sep.className = "lang-selector-sep";
      container.appendChild(sep);
    }
    var a = document.createElement("a");
    a.className = "lang-selector-link";
    a.textContent = lang.label;
    a.href = switchLangPath(lang.value);
    if (lang.value === currentLang) a.classList.add("active");
    container.appendChild(a);
  });

  // ── Insert into .right-buttons ──
  function insertSelector() {
    var rightButtons = document.querySelector(".right-buttons");
    if (rightButtons) {
      rightButtons.insertBefore(container, rightButtons.firstChild);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", insertSelector);
  } else {
    insertSelector();
  }
})();
