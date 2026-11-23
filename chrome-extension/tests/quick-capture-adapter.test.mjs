// Explanation contract: docs/EXPLAIN.md
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const extensionRoot = new URL("../", import.meta.url);

async function runOptionCapture(responseData, contentKind = "video", platform = "web", failureMode = "") {
  const listeners = {};
  const toasts = [];
  const timers = [];
  let complete;
  const document = {
    addEventListener(type, listener) { listeners[type] = listener; },
    createElement() {
      return { style: {}, textContent: "", remove() { this.removed = true; } };
    },
    documentElement: {
      appendChild(element) { toasts.push(element); },
    },
  };
  const chrome = {
    runtime: {
      lastError: null,
      sendMessage(_message, callback) {
        if (failureMode === "read") throw new Error("Unexpected submission after read failure");
        if (failureMode === "context") throw new Error("Extension context invalidated.");
        if (failureMode === "deferred") { complete = () => callback({ ok: true, data: responseData }); return; }
        callback({ ok: true, data: responseData });
      },
    },
  };
  if (failureMode === "runtime_missing") delete chrome.runtime;
  if (failureMode === "send_message_missing") delete chrome.runtime.sendMessage;
  const context = {
    chrome,
    console,
    document,
    setTimeout(callback, delay) { timers.push({ callback, delay }); return timers.length; },
  };
  const extractorSource = await readFile(new URL("extractor.js", extensionRoot), "utf8");
  vm.runInNewContext(extractorSource, context);
  Object.assign(context.__muyiVideoExtractor, {
    visibleMediaAt() { return {}; },
    async extractBestSelection() {
      if (failureMode === "read") throw new Error("读取期间作品发生变化，请重新点选当前素材");
      return {
        content_kind: contentKind,
        platform,
        page_url: platform === "x" ? "https://x.com/example/status/2094494202587398616" : "https://example.com/demo",
      };
    },
  });
  const source = await readFile(new URL("quick-capture.js", extensionRoot), "utf8");
  vm.runInNewContext(source, context);

  await listeners.pointerdown({
    altKey: true,
    button: 0,
    target: {},
    clientX: 100,
    clientY: 100,
    preventDefault() {},
    stopImmediatePropagation() {},
  });
  if (failureMode === "deferred") return { toasts, timers, complete };
  return toasts.at(-1);
}

test("option capture presents Adapter review state even when legacy status says saved", async () => {
  const toast = await runOptionCapture({
    status: "saved",
    failure_reason: "作品页已保留，真实媒体地址待补全",
    adapter: {
      contract_version: "muyi.capture-adapter.v1",
      operation: "collect_link",
      outcome: "needs_review",
      artifact_state: "link_pending",
      local_file_state: "not_created",
      retryable: true,
    },
  });

  assert.equal(toast.textContent, "作品页已保留，真实媒体地址待补全");
  assert.equal(toast.style.background, "#9a6a19");
});

test("option capture presents a pending X preview as pending rather than claiming background work", async () => {
  const toast = await runOptionCapture({
    status: "capture_pending",
    failure_reason: "没有取得可预览的真实媒体地址",
    adapter: {
      contract_version: "muyi.capture-adapter.v1",
      operation: "collect_link",
      outcome: "needs_review",
      artifact_state: "link_pending",
      local_file_state: "not_created",
      retryable: true,
    },
  }, "video", "x");

  assert.equal(toast.textContent, "已收藏到素材库，预览尚未就绪，可在素材库重试");
  assert.equal(toast.style.background, "#9a6a19");
});

test("option capture warns about missing original-note access even when the image was saved", async () => {
  const source_warning = "已收藏，但原笔记链接缺少访问参数";
  const toast = await runOptionCapture({ status: "saved", source_warning, adapter: { contract_version: "muyi.capture-adapter.v1", outcome: "success", artifact_state: "link_collected" } }, "image");
  assert.equal(toast.textContent, source_warning);
  assert.equal(toast.style.background, "#9a6a19");
});

test("option capture says the work is collected while its preview waits for preparation", async () => {
  const toast = await runOptionCapture({
    status: "saved",
    message: "已进入链接收集箱；真实媒体预览待激活",
    preview_message: "当前仅有 Blob 或空地址；可在需要时手动激活真实媒体预览",
    adapter: {
      contract_version: "muyi.capture-adapter.v1",
      operation: "collect_link",
      outcome: "success",
      artifact_state: "link_collected",
      local_file_state: "not_created",
      retryable: false,
    },
  });

  assert.equal(toast.textContent, "已进入链接收集箱；真实媒体预览待激活");
  assert.equal(toast.style.background, "#2f8f69");
});

test("option capture keeps direct video and image success messages unchanged", async () => {
  for (const [contentKind, label] of [["video", "视频"], ["image", "图片"]]) {
    const toast = await runOptionCapture({
      status: "saved",
      adapter: {
        contract_version: "muyi.capture-adapter.v1",
        operation: "collect_link",
        outcome: "success",
        artifact_state: "link_collected",
        local_file_state: "not_created",
        retryable: false,
      },
    }, contentKind);

    assert.equal(toast.textContent, `已收集${label} · 木易素材库`);
  }
});

test("capture stops submission on read failure and reports extension reload errors", async () => {
  const read = await runOptionCapture({}, "video", "web", "read");
  assert.match(read.textContent, /作品发生变化/);
  assert.equal(read.style.background, "#b94f59");
  const context = await runOptionCapture({}, "video", "web", "context");
  assert.equal(context.textContent, "采集扩展已更新，请刷新当前网页后重新点选");
  for (const mode of ["runtime_missing", "send_message_missing"]) {
    const missing = await runOptionCapture({}, "video", "web", mode);
    assert.equal(missing.textContent, "采集扩展已更新，请刷新当前网页后重新点选");
    assert.equal(missing.style.background, "#b94f59");
  }
});

 test("pending collection feedback stays visible until the asynchronous result arrives", async () => {
  const f = await runOptionCapture({ status: "capture_pending", preview_state: "resolving",
    adapter: { artifact_state: "link_pending", outcome: "needs_review" } }, "video", "x", "deferred");
  const working = f.toasts.at(-1);
  assert.match(working.textContent, /正在识别/);
  for (const timer of f.timers) timer.callback();
  assert.notEqual(working.removed, true);
  f.complete();
  assert.equal(working.removed, true);
  assert.equal(f.toasts.at(-1).textContent, "已收集视频；后台正在准备预览，可继续浏览");
  assert.ok(f.timers.some(timer => timer.delay === 10000));
});
