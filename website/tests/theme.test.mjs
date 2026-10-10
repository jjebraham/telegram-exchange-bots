import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";

const source = await readFile(new URL("../dist/theme.js", import.meta.url), "utf8");

function createThemePage(savedTheme, systemDark) {
  const storage = new Map(savedTheme ? [["alanchande-theme", savedTheme]] : []);
  const root = { dataset: {} };
  const listeners = new Map();
  const toggle = {
    label: "",
    setAttribute(name, value) { if (name === "aria-label") this.label = value; },
    addEventListener(name, listener) { listeners.set(name, listener); },
  };
  const document = {
    documentElement: root,
    readyState: "complete",
    getElementById(id) { return id === "theme-toggle" ? toggle : null; },
    addEventListener() {},
  };
  const window = { matchMedia: () => ({ matches: systemDark }) };
  const localStorage = {
    getItem(key) { return storage.get(key) ?? null; },
    setItem(key, value) { storage.set(key, value); },
  };

  runInNewContext(source, { document, window, localStorage });
  return { root, toggle, storage, click: () => listeners.get("click")() };
}

test("theme toggle follows system preference and persists the selection", () => {
  const page = createThemePage(null, true);
  assert.equal(page.root.dataset.theme, undefined);
  assert.equal(page.toggle.label, "روشن کردن حالت روشن");

  page.click();
  assert.equal(page.root.dataset.theme, "light");
  assert.equal(page.storage.get("alanchande-theme"), "light");
  assert.equal(page.toggle.label, "روشن کردن حالت تیره");
});

test("saved theme overrides the system preference", () => {
  const page = createThemePage("dark", false);
  assert.equal(page.root.dataset.theme, "dark");
  assert.equal(page.toggle.label, "روشن کردن حالت روشن");
});
