// Explanation contract: docs/EXPLAIN.md
(() => {
  if (globalThis.__muyiQuickCaptureInstalled) return;
  globalThis.__muyiQuickCaptureInstalled = true;
  let suppressClickUntil = 0;

  let activeToast = null;
  function showToast(message, tone = "success") {
    activeToast?.remove();
    const isReview = tone === "review";
    const isError = tone === true || tone === "error";
    const isWorking = tone === "working";
    const toast = document.createElement("div");
    toast.textContent = message;
    Object.assign(toast.style, {
      position: "fixed", zIndex: "2147483647", right: "22px", top: "22px",
      maxWidth: "360px", padding: "13px 17px", color: "#fff", borderRadius: "11px",
      background: isReview ? "#9a6a19" : isError ? "#b94f59" : isWorking ? "#3d6f9f" : "#2f8f69", boxShadow: "0 14px 42px #0004",
      font: '600 14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif',
    });
    document.documentElement.appendChild(toast);
    activeToast = toast;
    toast.setAttribute?.("role", "status");
    toast.setAttribute?.("aria-live", "polite");
    if (!isWorking) setTimeout(() => toast.remove(), 10000);
  }

  function onPointerOver(event) {
    globalThis.__muyiVideoExtractor?.rememberDouyinTarget(event.target);
  }

  async function onOptionPointerDown(event) {
    if (!event.altKey || event.button !== 0) return;
    const extractor = globalThis.__muyiVideoExtractor;
    const media = extractor?.visibleMediaAt(event.target, event.clientX, event.clientY);
    if (!media) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    suppressClickUntil = Date.now() + 1800;
    try {
      showToast("正在识别素材并收集，请稍候…", "working");
      const payload = await extractor.extractBestSelection(media);
      const kind = payload.content_kind === "image" ? "图片" : "视频";
      const runtime = globalThis.chrome?.runtime;
      if (typeof runtime?.sendMessage !== "function") throw new Error("Extension context invalidated.");
      runtime.sendMessage({ type: "muyi-capture-selected-media", payload }, (response) => {
        const failure = globalThis.chrome?.runtime?.lastError?.message || response?.error;
        if (failure || !response?.ok) {
          showToast(failure || "入库失败，请确认素材库已启动", true);
          return;
        }
        const data = response.data || {};
        const xPreviewCompleting = payload.platform === "x"
          && payload.content_kind === "video"
          && /^https:\/\/x\.com\/[^/]+\/status\/\d+/i.test(payload.page_url || "")
          && data?.adapter?.artifact_state === "link_pending"
          && data.preview_state !== "resolving";
        if (xPreviewCompleting) {
          showToast("已收藏到素材库，预览尚未就绪，可在素材库重试", "review");
          return;
        }
        if (data.preview_state === "resolving") {
          showToast("已收集视频；后台正在准备预览，可继续浏览");
          return;
        }
        if (extractor.captureNeedsReview(data)) {
          showToast(data.source_warning || data.failure_reason || "没有取得真实媒体地址，已保留作品页", "review");
          return;
        }
        if (data.preview_message) {
          showToast(data.message || "作品已收集，预览待准备");
          return;
        }
        showToast(data.duplicate
          ? `已更新该${kind}，没有生成重复卡片`
          : `已收集${kind} · 木易素材库`);
      });
    } catch (error) {
      const message = error?.message || "读取素材失败，请重新点选";
      showToast(/extension context invalidated/i.test(message)
        ? "采集扩展已更新，请刷新当前网页后重新点选" : message, "error");
    }
  }

  function suppressCapturedClick(event) {
    if (!event.altKey || Date.now() > suppressClickUntil) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  document.addEventListener("pointerover", onPointerOver, true);
  document.addEventListener("pointerdown", onOptionPointerDown, true);
  document.addEventListener("click", suppressCapturedClick, true);
})();
