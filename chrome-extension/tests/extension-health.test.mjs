import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const extensionRoot = new URL("../", import.meta.url);

function loadBackground({ pairingToken = "", fetchImpl = fetch, tabsImpl = {}, notificationsImpl = {} } = {}) {
  const listeners = {};
  const chrome = {
    action: { onClicked: { addListener(listener) { listeners.action = listener; } } },
    commands: { onCommand: { addListener(listener) { listeners.command = listener; } } },
    notifications: { async create() {}, ...notificationsImpl },
    runtime: {
      getManifest() { return { version: "0.4.5" }; },
      onMessage: { addListener(listener) { listeners.message = listener; } },
      async openOptionsPage() {},
    },
    scripting: { async executeScript() {} },
    storage: { local: { async get() { return { pairingToken }; } } },
    tabs: { async query() { return []; }, ...tabsImpl },
  };
  return readFile(new URL("background.js", extensionRoot), "utf8").then((source) => {
    vm.runInNewContext(source, { chrome, console, fetch: fetchImpl, setTimeout, URL });
    return listeners;
  });
}

async function submitCapture(listeners, payload) {
  return await new Promise((resolve) => {
    const keptOpen = listeners.message(
      { type: "muyi-capture-selected-media", payload },
      { tab: { id: 7, url: "https://www.douyin.com/search/换装" } },
      resolve,
    );
    assert.equal(keptOpen, true);
  });
}

test("health message wakes the service worker and reports its version", async () => {
  const listeners = await loadBackground();
  let response;
  const keptOpen = listeners.message(
    { type: "muyi-extension-health" },
    {},
    (payload) => { response = payload; },
  );

  assert.equal(keptOpen, false);
  assert.equal(response?.ok, true);
  assert.equal(response?.version, "0.4.5");
});

test("X collection uses only the paired capture endpoint and returns its resolved video", async () => {
  const calls = [];
  const complete = "https://video.twimg.com/amplify_video/2092807598437531648/vid/avc1/1280x720/full.mp4";
  const listeners = await loadBackground({ pairingToken: "fixture", fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, async json() { return { id: "capture-x", status: "saved", media_url: complete }; } };
  } });
  const response = await submitCapture(listeners, {
    platform: "x", content_kind: "video", external_id: "2092807747020689580",
    page_url: "https://x.com/lansenai/status/2092807747020689580", media_url: "blob:https://x.com/test",
  });
  assert.equal(response.data.media_url, complete);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:18778/api/captures");
  assert.equal(calls[0].options.headers["X-Muyi-Capture-Token"], "fixture");
});

test("blob and empty Douyin media are each collected once with exact work metadata", async () => {
  for (const mediaUrl of ["blob:https://www.douyin.com/temporary-player", ""]) {
    const calls = [];
    const listeners = await loadBackground({
      pairingToken: "paired-test-token",
      fetchImpl: async (url, options) => {
        calls.push({ url, options });
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              id: "capture-1",
              status: "saved",
              message: "已进入链接收集箱；真实媒体预览待激活",
              preview_message: "当前仅有 Blob 或空地址",
            };
          },
        };
      },
    });
    const payload = {
      content_kind: "video",
      platform: "douyin",
      page_url: "https://www.douyin.com/video/7671621304952327458",
      external_id: "7671621304952327458",
      page_title: "一招去掉 AI 大众脸",
      author_name: "@剪辑研究所",
      like_count_text: "3.3万",
      published_at_text: "2026-08-19 22:00",
      thumbnail_url: "https://p3-pc.douyinpic.com/obj/selected-cover.jpeg",
      thumbnail_external_id: "7671621304952327458",
      source_identity_verified: true,
      media_url: mediaUrl,
    };

    const response = await submitCapture(listeners, payload);

    assert.equal(response.ok, true);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "http://127.0.0.1:18778/api/captures");
    assert.equal(calls[0].options.method, "POST");
    const submitted = JSON.parse(calls[0].options.body);
    assert.deepEqual(submitted, { ...payload, save_only: true });
  }
});

test("XHS saves the selected note when the current page has no playable media", async () => {
  const noteId = "0123456789abcdef01234567";
  const pageUrl = `https://www.xiaohongshu.com/explore/\${noteId}?xsec_token=fixture`;
  let submitted = null;
  const listeners = await loadBackground({
    pairingToken: "fixture",
    tabsImpl: { async create() { assert.fail("publication must not read a background tab"); } },
    fetchImpl: async (_url, options) => {
      submitted = JSON.parse(options.body);
      return { ok: true, async json() { return { id: "capture-xhs", status: "capture_pending" }; } };
    },
  });
  const result = await submitCapture(listeners, {
    platform: "xiaohongshu", content_kind: "video", external_id: noteId,
    page_url: pageUrl, page_title: "合成笔记", media_url: "", source_identity_verified: true,
  });
  assert.equal(result.ok, true);
  assert.equal(submitted.external_id, noteId);
  assert.equal(submitted.page_url, pageUrl);
  assert.equal(submitted.media_url, "");
  assert.equal(submitted.save_only, true);
});

test("collection production sources forbid tab replacement, preview preparation, OpenCLI, and cookies", async () => {
  const productionFiles = [
    "background.js",
    "extractor.js",
    "quick-capture.js",
    "picker.js",
    "douyin-media-bridge.js",
  ];
  const forbidden = [
    /chrome\.tabs\.(?:create|update|sendMessage)\s*\(/,
    /\/preview\/prepare/,
    /opencli/i,
    /chrome\.cookies\b/,
  ];
  for (const filename of productionFiles) {
    const source = await readFile(new URL(filename, extensionRoot), "utf8");
    for (const pattern of forbidden) {
      assert.doesNotMatch(source, pattern, `${filename} contains forbidden collection call ${pattern}`);
    }
  }

  const manifest = JSON.parse(await readFile(new URL("manifest.json", extensionRoot), "utf8"));
  assert.equal((manifest.permissions || []).includes("cookies"), false);
});


test("backend validation failure reaches caller even when notifications fail", async () => {
  const notifications = [];
  const listeners = await loadBackground({
    pairingToken: "paired-test-token",
    fetchImpl: async () => ({ ok: false, status: 400, async json() { return { error: "作品身份不一致" }; } }),
    notificationsImpl: { async create(data) { notifications.push(data); throw new Error("notifications unavailable"); } },
  });
  const response = await submitCapture(listeners, { platform: "web" });
  assert.equal(response.ok, false);
  assert.equal(response.error, "作品身份不一致");
  assert.equal(notifications[0].message, "作品身份不一致");
  assert.equal(notifications[0].title, "素材收集失败");
});
