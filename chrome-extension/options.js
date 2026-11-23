// Explanation contract: docs/EXPLAIN.md
const tokenInput = document.querySelector("#token");
const status = document.querySelector("#status");
const workerStatus = document.querySelector("#worker-status");

async function checkExtensionWorker() {
  try {
    const result = await chrome.runtime.sendMessage({ type: "muyi-extension-health" });
    if (!result?.ok) throw new Error("插件未响应");
    workerStatus.textContent = `插件运行正常（v${result.version}）。Chrome 显示“Service Worker 无效”只表示空闲休眠，采集时会自动唤醒。`;
  } catch {
    workerStatus.textContent = "插件没有响应，请在 Chrome 扩展管理页点一次“重新加载”。";
  }
}

chrome.storage.local.get("pairingToken").then(({ pairingToken = "" }) => {
  tokenInput.value = pairingToken;
});

checkExtensionWorker();

document.querySelector("#reload-extension").addEventListener("click", () => {
  chrome.runtime.reload();
});

document.querySelector("#save").addEventListener("click", async () => {
  const pairingToken = tokenInput.value.trim();
  if (!pairingToken) {
    status.textContent = "请先粘贴配对令牌。";
    return;
  }
  try {
    const response = await fetch("http://127.0.0.1:18778/api/captures/pair", {
      method: "POST",
      headers: { "X-Muyi-Capture-Token": pairingToken },
    });
    if (response.status === 403) {
      status.textContent = "配对令牌不正确，请从正在运行的素材库重新复制。";
      return;
    }
    if (!response.ok) throw new Error();
    await chrome.storage.local.set({ pairingToken });
    status.textContent = "配对成功，可以返回网页点选素材。";
  } catch {
    status.textContent = "还没有连上素材库。请先打开独立版，再试一次。";
  }
});
