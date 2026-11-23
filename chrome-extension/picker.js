// Explanation contract: docs/EXPLAIN.md
(() => {
  const existingCleanup = globalThis.__muyiVideoPickerCleanup;
  if (typeof existingCleanup === "function") existingCleanup();

  const STYLE_ID = "muyi-video-picker-style";
  const HIGHLIGHT_ID = "muyi-video-picker-highlight";
  const GUIDE_ID = "muyi-video-picker-guide";
  let selectedMedia = null;

  document.getElementById(STYLE_ID)?.remove();
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    #${HIGHLIGHT_ID}{position:fixed;z-index:2147483646;pointer-events:none;border:3px solid #7c5ce5;border-radius:12px;background:#7c5ce51a;box-shadow:0 0 0 9999px #16101f26,0 10px 32px #2d1d5f35;transition:all .06s ease}
    #${GUIDE_ID}{position:fixed;z-index:2147483647;left:50%;top:18px;transform:translateX(-50%);padding:12px 18px;color:#fff;border-radius:12px;background:#241c32ef;box-shadow:0 12px 38px #0005;font:600 14px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;pointer-events:none}
    .muyi-picker-toast{position:fixed;z-index:2147483647;right:22px;top:22px;max-width:360px;padding:13px 17px;color:#fff;border-radius:11px;background:#2f8f69;box-shadow:0 14px 42px #0004;font:600 14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}
    .muyi-picker-toast.error{background:#b94f59}
  `;
  document.documentElement.appendChild(style);

  const highlight = document.createElement("div");
  highlight.id = HIGHLIGHT_ID;
  highlight.hidden = true;
  const guide = document.createElement("div");
  guide.id = GUIDE_ID;
  guide.textContent = "移动鼠标选择视频或图片；X 视频会读取真实媒体地址 · Esc 取消";
  document.documentElement.append(highlight, guide);

  function cleanText(value, maxLength = 500) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
  }

  function visibleMediaAt(target, x, y) {
    if (globalThis.__muyiVideoExtractor?.visibleMediaAt) {
      return globalThis.__muyiVideoExtractor.visibleMediaAt(target, x, y);
    }
    let current = target;
    for (let depth = 0; current && depth < 9; depth += 1, current = current.parentElement) {
      const mediaItems = current.matches?.("video, img[src]") ? [current] : [...(current.querySelectorAll?.("video, img[src]") || [])];
      const match = mediaItems.find((media) => {
        const rect = media.getBoundingClientRect();
        const css = getComputedStyle(media);
        return rect.width > 40 && rect.height > 40 && x >= rect.left && x <= rect.right &&
          y >= rect.top && y <= rect.bottom && css.display !== "none" && css.visibility !== "hidden";
      });
      if (match) return match;
    }
    return null;
  }

  function contextFor(media) {
    let best = media.parentElement || media;
    let current = best;
    const selector = media?.tagName?.toLowerCase?.() === "img" ? "img[src]" : "video";
    for (let depth = 0; current?.parentElement && depth < 8; depth += 1) {
      current = current.parentElement;
      const rect = current.getBoundingClientRect();
      const visibleMedia = [...current.querySelectorAll(selector)].filter((item) => {
        const itemRect = item.getBoundingClientRect();
        return itemRect.width > 40 && itemRect.height > 40;
      });
      if (visibleMedia.length !== 1) break;
      if (rect.width <= innerWidth * 1.15 && rect.height <= innerHeight * 1.5) best = current;
    }
    return best;
  }

  function preferredLink(container) {
    const anchors = [];
    let current = container;
    for (let depth = 0; current && depth < 7; depth += 1, current = current.parentElement) {
      if (current.matches?.("a[href]")) anchors.push(current);
      anchors.push(...(current.querySelectorAll?.("a[href]") || []));
    }
    const unique = [...new Set(anchors)].filter((anchor) => /^https?:/.test(anchor.href || ""));
    const preferred = unique.find((anchor) => /\/(video|note|explore|watch|shorts)\//i.test(anchor.href)) ||
      unique.find((anchor) => /\/video\/\d+/i.test(anchor.href));
    return preferred?.href || document.querySelector('meta[property="og:url"]')?.content || location.href;
  }

  function platformFor(url) {
    const host = new URL(url, location.href).hostname.toLowerCase();
    if (host.endsWith("douyin.com")) return "douyin";
    if (host.endsWith("xiaohongshu.com") || host.endsWith("xhslink.com")) return "xiaohongshu";
    if (host.endsWith("bilibili.com") || host.endsWith("b23.tv")) return "bilibili";
    if (host.endsWith("x.com") || host.endsWith("twitter.com")) return "x";
    if (host.endsWith("youtube.com") || host.endsWith("youtu.be")) return "youtube";
    return host.replace(/^www\./, "").slice(0, 80) || "web";
  }

  function externalIdFor(url) {
    const patterns = [
      /\/video\/(\d{8,})/i,
      /\/(?:explore|discovery\/item)\/([a-zA-Z0-9]+)/i,
      /\/video\/([A-Za-z0-9]+)/i,
      /\/(BV[0-9A-Za-z]+)/,
      /[?&](?:item_id|modal_id|video_id|v)=([^&#]+)/i,
    ];
    for (const pattern of patterns) {
      const match = String(url).match(pattern);
      if (match) return match[1].slice(0, 300);
    }
    return "";
  }

  function usefulLine(value) {
    const ignored = /^(点赞|评论|分享|收藏|关注|不感兴趣|更多|播放|暂停|\d+[wW万]?|音乐)$/;
    return String(value || "").split(/\n+/).map((line) => cleanText(line, 220))
      .find((line) => line.length >= 4 && !ignored.test(line));
  }

  function extractSelection(media) {
    if (globalThis.__muyiVideoExtractor) {
      return globalThis.__muyiVideoExtractor.extractSelection(media);
    }
    const context = contextFor(media);
    const pageUrl = preferredLink(context);
    const titleSelectors = [
      '[data-e2e*="desc"]', '[data-e2e*="title"]', '[class*="title"]',
      '[class*="desc"]', '[aria-label]', 'h1', 'h2', 'h3', 'img[alt]',
    ];
    let pageTitle = "";
    for (const selector of titleSelectors) {
      const node = context.querySelector?.(selector);
      const value = node?.getAttribute?.("aria-label") || node?.getAttribute?.("alt") || node?.textContent;
      pageTitle = usefulLine(value) || "";
      if (pageTitle) break;
    }
    pageTitle ||= usefulLine(context.innerText);
    pageTitle ||= cleanText(document.querySelector('meta[property="og:title"]')?.content, 500);
    const isImage = media?.tagName?.toLowerCase?.() === "img";
    pageTitle ||= cleanText(media?.alt || media?.title, 500);
    pageTitle ||= cleanText(document.title, 500) || (isImage ? "未命名网页图片" : "未命名网页视频");

    const authorNode = context.querySelector?.(
      '[data-e2e*="author"], [class*="author"], a[href*="/user/"], a[href*="/profile/"], a[href*="/space/"]'
    );
    const authorName = usefulLine(authorNode?.textContent || authorNode?.getAttribute?.("aria-label")) || "";
    const image = context.querySelector?.("img[src]");
    const thumbnailUrl = isImage ? (media.currentSrc || media.src || "") : media.poster || image?.currentSrc || image?.src ||
      document.querySelector('meta[property="og:image"]')?.content || "";
    const mediaUrl = media.currentSrc || media.src || media.querySelector?.("source")?.src || "";
    return {
      content_kind: isImage ? "image" : "video",
      page_title: cleanText(pageTitle, 500),
      page_url: pageUrl,
      media_url: mediaUrl,
      platform: platformFor(pageUrl),
      author_name: cleanText(authorName, 300),
      thumbnail_url: thumbnailUrl,
      external_id: externalIdFor(pageUrl),
    };
  }

  let activeToast = null;
  function showToast(message, tone = "success") {
    activeToast?.remove();
    const isReview = tone === "review";
    const isError = tone === true || tone === "error";
    const isWorking = tone === "working";
    const toast = document.createElement("div");
    toast.className = `muyi-picker-toast${isReview ? " review" : isError ? " error" : ""}`;
    toast.textContent = message;
    Object.assign(toast.style, {
      position: "fixed",
      zIndex: "2147483647",
      right: "22px",
      top: "22px",
      maxWidth: "360px",
      padding: "13px 17px",
      color: "#fff",
      borderRadius: "11px",
      background: isReview ? "#9a6a19" : isError ? "#b94f59" : isWorking ? "#3d6f9f" : "#2f8f69",
      boxShadow: "0 14px 42px #0004",
      font: '600 14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif',
    });
    document.documentElement.appendChild(toast);
    activeToast = toast;
    toast.setAttribute?.("role", "status");
    toast.setAttribute?.("aria-live", "polite");
    if (!isWorking) setTimeout(() => toast.remove(), 10000);
  }

  function cleanup() {
    document.removeEventListener("mousemove", onMove, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKey, true);
    highlight.remove();
    guide.remove();
    style.remove();
    delete globalThis.__muyiVideoPickerCleanup;
  }

  function onMove(event) {
    selectedMedia = visibleMediaAt(event.target, event.clientX, event.clientY);
    if (!selectedMedia) {
      highlight.hidden = true;
      return;
    }
    const rect = selectedMedia.getBoundingClientRect();
    highlight.hidden = false;
    Object.assign(highlight.style, {
      left: `${Math.max(0, rect.left)}px`,
      top: `${Math.max(0, rect.top)}px`,
      width: `${Math.min(innerWidth, rect.right) - Math.max(0, rect.left)}px`,
      height: `${Math.min(innerHeight, rect.bottom) - Math.max(0, rect.top)}px`,
    });
  }

  async function onClick(event) {
    const media = visibleMediaAt(event.target, event.clientX, event.clientY) || selectedMedia;
    if (!media) {
      guide.textContent = "这里没有可见视频或图片，请点击素材画面 · Esc 取消";
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    try {
      const payloadPromise = globalThis.__muyiVideoExtractor?.extractBestSelection(media)
        || Promise.resolve(extractSelection(media));
      cleanup();
      showToast("正在识别素材并收集，请稍候…", "working");
      const payload = await payloadPromise;
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
        if (globalThis.__muyiVideoExtractor?.captureNeedsReview(data)) {
          showToast(data.source_warning || data.failure_reason || "没有取得真实媒体地址，已保留作品页", "review");
          return;
        }
        if (data.preview_message) {
          showToast(data.message || "作品已收集，预览待准备");
          return;
        }
        showToast(data.duplicate ? `已更新该${kind}，没有生成重复卡片` : `已收集${kind} · 木易素材库`);
      });
    } catch (error) {
      const message = error?.message || "读取素材失败，请重新点选";
      showToast(/extension context invalidated/i.test(message)
        ? "采集扩展已更新，请刷新当前网页后重新点选" : message, "error");
    }
  }

  function onKey(event) {
    if (event.key !== "Escape") return;
    cleanup();
    showToast("已取消采集");
  }

  document.addEventListener("mousemove", onMove, true);
  document.addEventListener("click", onClick, true);
  document.addEventListener("keydown", onKey, true);
  globalThis.__muyiVideoPickerCleanup = cleanup;
})();
