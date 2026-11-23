import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const extensionRoot = new URL("../", import.meta.url);

test("options page explains that an idle worker is healthy after waking it", async () => {
  const elements = new Map();
  const elementListeners = new Map();
  for (const selector of ["#token", "#status", "#worker-status", "#save", "#reload-extension"]) {
    elements.set(selector, {
      value: "",
      textContent: "",
      addEventListener(type, listener) { elementListeners.set(`${selector}:${type}`, listener); },
    });
  }
  const messages = [];
  let reloadCount = 0;
  const chrome = {
    runtime: {
      reload() { reloadCount += 1; },
      async sendMessage(message) {
        messages.push(message);
        return { ok: true, version: "0.4.6" };
      },
    },
    storage: {
      local: {
        async get() { return { pairingToken: "" }; },
        async set() {},
      },
    },
  };
  const source = await readFile(new URL("options.js", extensionRoot), "utf8");
  vm.runInNewContext(source, {
    chrome,
    document: { querySelector(selector) { return elements.get(selector); } },
    fetch,
    console,
  });
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.type, "muyi-extension-health");
  assert.match(elements.get("#worker-status").textContent, /插件运行正常/);
  assert.match(elements.get("#worker-status").textContent, /空闲休眠/);
  assert.match(elements.get("#worker-status").textContent, /0\.4\.6/);

  elementListeners.get("#reload-extension:click")();
  assert.equal(reloadCount, 1);
});
