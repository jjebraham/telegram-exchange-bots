(() => {
  const root = document.documentElement;
  const storageKey = "alanchande-theme";

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  } catch {
    // The system theme remains available when browser storage is disabled.
  }

  const currentTheme = () => root.dataset.theme
    || (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  const initialize = () => {
    const toggle = document.getElementById("theme-toggle");
    if (!toggle) return;

    const updateLabel = () => {
      toggle.setAttribute("aria-label", currentTheme() === "dark"
        ? "روشن کردن حالت روشن"
        : "روشن کردن حالت تیره");
    };

    updateLabel();
    toggle.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        // The selected theme still applies for this page view.
      }
      updateLabel();
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
