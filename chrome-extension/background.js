// Explanation contract: docs/EXPLAIN.md
const SERVICE_URL = "http://127.0.0.1:18778";

async function notify(title, message) {
  await chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
}

async function requirePairingToken() {
  const { pairingToken = "" } = await chrome.storage.local.get("pairingToken");
  if (pairingToken) return pairingToken;
  await notify("木易素材库尚未配对", "已打开设置页，请粘贴素材库中的配对令牌。");
  await chrome.runtime.openOptionsPage();
  return "";
}

async function activatePicker() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/^https?:/.test(tab.url || "")) {
    await notify("木易素材库", "当前页面不能读取，请打开普通网页后再试。");
    return;
  }
  if (!await requirePairingToken()) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["extractor.js", "picker.js"],
    });
  } catch (_error) {
    await notify("无法在当前页面点选", "请刷新网页后再试，浏览器内部页面不支持采集。");
  }
}

async function submitSelection(payload) {
  const pairingToken = await requirePairingToken();
  if (!pairingToken) throw new Error("扩展尚未配对");
  const response = await fetch(`${SERVICE_URL}/api/captures`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Muyi-Capture-Token": pairingToken,
    },
    body: JSON.stringify({ ...payload, save_only: true }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `服务返回 ${response.status}`);
  return data;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "muyi-extension-health") {
    sendResponse({ ok: true, version: chrome.runtime.getManifest().version });
    return false;
  }
  if (!["muyi-capture-selected-media", "muyi-capture-selected-video"].includes(message?.type)) return false;
  if (!sender.tab?.id || !/^https?:/.test(sender.tab.url || "")) {
    sendResponse({ ok: false, error: "只能收集当前打开的普通网页" });
    return false;
  }
  submitSelection(message.payload || {})
    .then((data) => sendResponse({ ok: true, data }))
    .catch(async (error) => {
      const message = error?.message || "入库失败";
      // Return the actual result even when system notifications are unavailable.
      sendResponse({ ok: false, error: message });
      try { await notify("素材收集失败", message); } catch (_notificationError) {}
    });
  return true;
});

chrome.commands.onCommand.addListener((command) => {
  if (command === "capture-visible-video") activatePicker();
});

chrome.action.onClicked.addListener(() => activatePicker());
