// Explanation contract: docs/EXPLAIN.md
(() => {
  if (globalThis.__muyiDouyinMediaBridgeInstalled) return;
  globalThis.__muyiDouyinMediaBridgeInstalled = true;

  const META_NAME = "muyi-media-candidate";
  const requestUrlKey = Symbol("muyiDetailRequestUrl");

  function detailApiUrl(value) {
    try {
      const url = new URL(String(value?.url || value || ""), location.href);
      if (url.origin !== location.origin) return null;
      if (!/^\/aweme\/v1\/web\/aweme\/detail\/?$/.test(url.pathname)) return null;
      return url;
    } catch (_error) {
      return null;
    }
  }

  function firstHttpsUrl(address) {
    const urls = address?.url_list || address?.urlList || [];
    return (Array.isArray(urls) ? urls : []).find((url) => /^https:\/\//i.test(String(url || ""))) || "";
  }

  function detailCandidate(payload) {
    const detail = payload?.aweme_detail || payload?.awemeDetail || null;
    const videoId = String(detail?.aweme_id || detail?.awemeId || "");
    const authorName = String(detail?.author?.nickname || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 100);
    const video = detail?.video || {};
    const mediaUrl = firstHttpsUrl(video.play_addr_h264 || video.playAddrH264)
      || firstHttpsUrl(video.play_addr || video.playAddr)
      || firstHttpsUrl(video.download_addr || video.downloadAddr);
    const coverUrl = firstHttpsUrl(video.origin_cover || video.originCover)
      || firstHttpsUrl(video.cover)
      || firstHttpsUrl(video.dynamic_cover || video.dynamicCover);
    if (!/^\d+$/.test(videoId) || (!mediaUrl && !coverUrl && !authorName)) return null;
    return { videoId, mediaUrl, coverUrl, authorName };
  }

  function publish(payload) {
    const candidate = detailCandidate(payload);
    if (!candidate || !document.documentElement) return;
    const metas = [...document.querySelectorAll(`meta[name="${META_NAME}"]`)];
    let meta = metas.find((node) => node.dataset.videoId === candidate.videoId);
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = META_NAME;
      document.documentElement.append(meta);
    }
    meta.dataset.videoId = candidate.videoId;
    meta.dataset.mediaUrl = candidate.mediaUrl;
    meta.dataset.coverUrl = candidate.coverUrl;
    meta.dataset.authorName = candidate.authorName;
  }

  async function inspectFetchResponse(response, requestUrl) {
    if (!detailApiUrl(requestUrl)) return;
    try {
      publish(await response.clone().json());
    } catch (_error) {
      // 不影响抖音自己的响应；无法读取时让采集器明确保持待补全。
    }
  }

  const originalFetch = globalThis.fetch;
  if (typeof originalFetch === "function") {
    globalThis.fetch = function muyiCapturedFetch(...args) {
      const requestUrl = args[0]?.url || args[0] || "";
      const result = originalFetch.apply(this, args);
      Promise.resolve(result).then((response) => inspectFetchResponse(response, requestUrl)).catch(() => {});
      return result;
    };
  }

  const originalOpen = globalThis.XMLHttpRequest?.prototype?.open;
  const originalSend = globalThis.XMLHttpRequest?.prototype?.send;
  if (typeof originalOpen === "function" && typeof originalSend === "function") {
    globalThis.XMLHttpRequest.prototype.open = function muyiCapturedOpen(method, url, ...args) {
      this[requestUrlKey] = detailApiUrl(url)?.href || "";
      return originalOpen.call(this, method, url, ...args);
    };
    globalThis.XMLHttpRequest.prototype.send = function muyiCapturedSend(...args) {
      if (this[requestUrlKey]) {
        this.addEventListener("load", () => {
          try {
            const payload = this.responseType === "json" ? this.response : JSON.parse(this.responseText || "");
            publish(payload);
          } catch (_error) {
            // 不修改原请求；无法读取时只是不发布媒体候选。
          }
        }, { once: true });
      }
      return originalSend.apply(this, args);
    };
  }

  globalThis.__muyiDouyinMediaBridge = { detailCandidate, publish };
})();
