// Explanation contract: docs/EXPLAIN.md
(() => {
  if (globalThis.__muyiVideoExtractor) return;

  const PLAYER_SELECTOR = 'video, xg-video-container, xg-controls, xg-icon, xg-slider, [class*="xgplayer"], [data-xgplayerid]';
  const douyinLikeCache = new Map();
  const xPlaybackUrls = new Map();

  // X can evict early playlist requests while a video keeps playing from a
  // Blob. Retain only observed playback URLs, bounded to this page's lifetime.
  if (typeof location !== "undefined" && ["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(location.hostname)
      && typeof PerformanceObserver !== "undefined") {
    const remember = entries => {
      for (const entry of entries) {
        if (xStreamScore(entry.name) < 0) continue;
        xPlaybackUrls.delete(entry.name);
        xPlaybackUrls.set(entry.name, true);
        if (xPlaybackUrls.size > 200) xPlaybackUrls.delete(xPlaybackUrls.keys().next().value);
      }
    };
    try {
      remember(performance.getEntriesByType("resource"));
      const observer = new PerformanceObserver(list => remember(list.getEntries()));
      observer.observe({ type: "resource", buffered: true });
    } catch (_error) { /* The current player's direct URL remains available. */ }
  }

  function cleanText(value, maxLength = 500) {
    return String(value || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim().slice(0, maxLength);
  }

  function unique(values) {
    return [...new Set((values || []).map((value) => cleanText(value)).filter(Boolean))];
  }

  function looksLikeDuration(value) {
    return /^\d{1,2}:\d{2}(?::\d{2})?(?:\s*\/\s*\d{1,2}:\d{2}(?::\d{2})?)?$/.test(cleanText(value));
  }

  function looksLikeMetric(value) {
    return /^(?:(?:点赞|获赞|评论|收藏|分享|播放)\s*[:：]?\s*)?[\d.,]+\s*(?:万|亿|[kKmMwW])?$/.test(cleanText(value));
  }

  function looksLikePublishTime(value) {
    return /(?:发布时间[:：]\s*)?\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?(?:\s+\d{1,2}:\d{2})?|\d{1,2}月\d{1,2}日|\d+\s*(?:分钟|小时|天|周|个月|月|年)前|昨天(?:\s*\d{1,2}:\d{2})?|今天(?:\s*\d{1,2}:\d{2})?|前天|刚刚/.test(cleanText(value));
  }

  function isJunkTitle(value) {
    const text = cleanText(value, 300);
    if (!text || text.length < 3 || text.length > 260) return true;
    if (looksLikeDuration(text) || looksLikeMetric(text) || looksLikePublishTime(text)) return true;
    if (/^(?:Tag\s*[:：]\s*)?(?:置顶|广告|直播|搜索|综合|视频|用户|经验|商品|Embedded video)$/i.test(text)) return true;
    if (/^(?:点赞|评论|分享|收藏|关注|不感兴趣|更多|播放|暂停|音乐)$/i.test(text)) return true;
    if (/^(?:点击)?按住.*(?:拖动|视频)$/i.test(text)) return true;
    if (/^(?:抖音[-｜| ]*)?记录美好生活$/i.test(text)) return true;
    if (/^正在识别素材并收集|^已收集(?:图片|视频) · 木易素材库/.test(text)) return true;
    return /^https?:\/\//i.test(text);
  }

  function titleScore(value, index) {
    const text = cleanText(value, 300);
    if (isJunkTitle(text)) return -1;
    let score = Math.min(text.length, 120) + Math.max(0, 30 - index * 3);
    if (/[#？?！!，。；：]/.test(text)) score += 25;
    if (/[\u4e00-\u9fff]{4,}/.test(text)) score += 20;
    return score;
  }

  function cleanAuthor(value) {
    const text = cleanText(value, 100).replace(/^作者\s*[:：]\s*/, "");
    if (!text || text.length < 2 || text.length > 80) return "";
    if (looksLikeDuration(text) || looksLikeMetric(text) || looksLikePublishTime(text)) return "";
    if (/^(?:Tag\s*[:：]\s*)?(?:置顶|关注|点赞|评论|收藏|分享|音乐)$/i.test(text)) return "";
    return text;
  }

  function videoIdFor(href, elementId = "") {
    const urlText = cleanText(href, 4000);
    try {
      const url = new URL(urlText || "/", "https://www.douyin.com/");
      const params = url.searchParams;
      // A search modal can retain /video/<previous-id>/search/... underneath.
      // Its explicit modal identity belongs to the work currently being shown.
      for (const key of ["modal_id", "vid"]) {
        const candidate = params.get(key) || "";
        if (/^\d{8,}$/.test(candidate)) return candidate;
      }
      const pathId = url.pathname.match(/^\/video\/(\d{8,})\/?$/i)?.[1] || "";
      if (pathId) return pathId;
      for (const key of ["item_id", "video_id"]) {
        const candidate = params.get(key) || "";
        if (/^\d{8,}$/.test(candidate)) return candidate;
      }
    } catch (_error) {
      // 继续尝试卡片元素 ID。
    }
    return cleanText(elementId).match(/waterfall_item_(\d{8,})/)?.[1] || "";
  }

  function extractPublishTime(snapshot) {
    const lines = unique([...(snapshot.metaTexts || []), ...String(snapshot.cardText || "").split(/\r?\n/)])
      .map((line) => cleanText(line).replace(/^[·•]\s*/, ""));
    const explicit = lines.join(" · ").match(/发布时间[:：]\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2})?)/);
    if (explicit) return explicit[1];
    const absolute = lines.find((line) => /^(?:\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?|\d{1,2}月\d{1,2}日)(?:\s+\d{1,2}:\d{2})?$/.test(line));
    if (absolute) return absolute;
    return lines.find((line) => /^(?:\d+\s*(?:分钟|小时|天|周|个月|月|年)前|昨天(?:\s*\d{1,2}:\d{2})?|今天(?:\s*\d{1,2}:\d{2})?|前天|刚刚)$/.test(line)) || "";
  }

  function extractLikeText(snapshot) {
    for (const value of unique(snapshot.likeTexts || [])) {
      if (/获赞/.test(value)) continue; // Author totals are not this work's likes.
      const labeled = value.match(/点赞\s*[:：]?\s*([\d.,]+\s*(?:万|亿|[kKmMwW])?)/i);
      if (labeled) return cleanText(labeled[1], 120);
      if (looksLikeMetric(value) && !looksLikeDuration(value)) return cleanText(value, 120);
    }
    const line = unique(snapshot.metaTexts || []).find((value) => !/获赞/.test(value) && /点赞\s*[:：]?\s*\d/i.test(value));
    return cleanText(line?.match(/点赞\s*[:：]?\s*([\d.,]+\s*(?:万|亿|[kKmMwW])?)/i)?.[1], 120);
  }

  function normalizeDouyinSnapshot(snapshot = {}) {
    const pageVideoId = videoIdFor(snapshot.pageUrl, "");
    const elementVideoId = videoIdFor("", snapshot.elementId);
    const rawFeedId = cleanText(snapshot.feedVideoId);
    const feedVideoId = /^\d{8,}$/.test(rawFeedId) ? rawFeedId : "";
    const anchorVideoId = videoIdFor(snapshot.href, "");
    const strongIdentityConflict = unique([pageVideoId, elementVideoId, feedVideoId]).length > 1
      || (rawFeedId && !feedVideoId);
    const videoId = strongIdentityConflict ? "" : (pageVideoId || elementVideoId || feedVideoId || anchorVideoId);
    const pageUrl = videoId ? `https://www.douyin.com/video/${videoId}` : cleanText(snapshot.href || snapshot.pageUrl, 4000);
    const pageTitle = unique([...(snapshot.titleCandidates || []), ...String(snapshot.cardText || "").split(/\r?\n/)])
      .map((text, index) => ({ text, score: titleScore(text, index) }))
      .filter((item) => item.score >= 0)
      .sort((left, right) => right.score - left.score)[0]?.text
      || unique(snapshot.fallbackTitleCandidates || [])
        .map((text, index) => ({ text, score: titleScore(text, index) }))
        .filter((item) => item.score >= 0)
        .sort((left, right) => right.score - left.score)[0]?.text
      || "";
    const explicitAuthors = unique(snapshot.authorTexts || []).map(cleanAuthor).filter(Boolean);
    const metaAuthors = unique(snapshot.metaTexts || [])
      .filter((line) => /^@[^\r\n]{2,80}$/.test(line) || /^作者\s*[:：]/.test(line))
      .map(cleanAuthor).filter(Boolean);
    return {
      page_title: pageTitle,
      page_url: pageUrl,
      platform: "douyin",
      author_name: explicitAuthors[0] || metaAuthors[0] || "",
      external_id: videoId,
      source_identity_verified: Boolean(videoId),
      like_count_text: extractLikeText(snapshot),
      published_at_text: extractPublishTime(snapshot),
    };
  }

  function isVisible(element) {
    if (!element?.getBoundingClientRect) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  }

  function backgroundImageUrl(element) {
    if (!element || typeof getComputedStyle !== "function") return "";
    const value = getComputedStyle(element).backgroundImage || "";
    const match = value.match(/url\((['"]?)(.*?)\1\)/i);
    const url = cleanText(match?.[2], 8000);
    return /^https?:\/\//i.test(url) ? url : "";
  }

  function mediaKindFor(media) {
    const tag = media?.tagName?.toLowerCase?.();
    if (tag === "video") return "video";
    if (tag === "img" || backgroundImageUrl(media)) return "image";
    return "";
  }

  function mediaUrlFor(media) {
    const kind = mediaKindFor(media);
    if (kind === "video") {
      return media.currentSrc || media.src || media.querySelector?.("source")?.src || "";
    }
    if (kind === "image") return media.currentSrc || media.src || backgroundImageUrl(media) || "";
    return "";
  }

  function originalImageUrlFor(media) {
    const displayed = mediaUrlFor(media);
    try {
      const current = new URL(displayed);
      if (current.protocol === "https:" && current.hostname === "pbs.twimg.com"
          && current.pathname.startsWith("/media/") && current.searchParams.has("name")) {
        current.searchParams.set("name", "orig");
        return current.href;
      }
      if (!media.srcset?.trim()) return displayed;
      const candidates = media.srcset.split(",").map(item => {
        const match = item.trim().match(/^(\S+)\s+(\d+(?:\.\d+)?)(w|x)$/);
        if (!match) return null;
        const url = new URL(match[1], media.baseURI || current.href);
        if (!["https:", "http:"].includes(url.protocol)) return null;
        return { url: url.href, size: Number(match[2]), unit: match[3] };
      });
      if (candidates.some(item => !item || item.unit !== candidates[0]?.unit)
          || !candidates.some(item => item.url === current.href)) return displayed;
      return candidates.sort((a, b) => b.size - a.size)[0].url;
    } catch (_error) {
      return displayed;
    }
  }

  function xVideoPosterUrl(media) {
    // A tweet's video poster is evidence even before X creates a <video> node.
    // Never search a whole tweet for a cover: it may contain several media items.
    for (const value of [media?.poster, media?.getAttribute?.("poster"), media?.currentSrc, media?.src, backgroundImageUrl(media)]) {
      try {
        const url = new URL(String(value || ""));
        if (url.protocol === "https:" && url.hostname === "pbs.twimg.com" && !url.username && !url.password
            && /^\/(?:amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)\/\d{8,}\//i.test(url.pathname)) return url.href;
      } catch (_error) { /* Not an identifiable X video cover. */ }
    }
    return "";
  }

  function xMediaIdFor(media) {
    return xVideoPosterUrl(media).match(/\/(?:amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)\/(\d{8,})\//i)?.[1] || "";
  }

  function xStreamScore(url) {
    let parsed;
    try { parsed = new URL(url); } catch (_error) { return -1; }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port
        || parsed.hostname.toLowerCase() !== "video.twimg.com") return -1;
    const path = parsed.pathname;
    // Fragmented playback exposes a tiny .mp4 initialization header at /0/0/;
    // it contains no frames. Keep the observed playlist instead of that header.
    if (/\/aud\/|\/vid\/[^/]+\/\d+\/\d+\//i.test(path)) return -1;
    let score = /\.mp4$/i.test(path) ? 300 : /\.m3u8$/i.test(path) ? 200 : -1;
    if (score < 0) return score;
    if (/\/master\.m3u8$/i.test(path)) score += 80;
    if (/\/pl\/[^/]+\.m3u8$/i.test(path)) score += 50;
    const resolution = path.match(/\/(\d{2,5})x(\d{2,5})\//);
    if (resolution) score += Math.min(50, Number(resolution[1]) * Number(resolution[2]) / 100000);
    return score;
  }

  function xMediaStreamUrl(media, resourceUrls = null) {
    const mediaId = xMediaIdFor(media);
    if (!mediaId) return "";
    const observed = resourceUrls || (typeof performance !== "undefined"
      ? performance.getEntriesByType("resource").map((entry) => entry.name)
      : []);
    const candidates = unique([media?.currentSrc, media?.src, ...(observed || []), ...xPlaybackUrls.keys()])
      .filter((url) => String(url).includes(`/${mediaId}/`))
      .map((url) => ({ url, score: xStreamScore(url) }))
      .filter((item) => item.score >= 0)
      .sort((left, right) => right.score - left.score || left.url.length - right.url.length);
    return candidates[0]?.url || "";
  }

  function douyinMediaStreamUrl(media, videoId, capturedCandidates = null) {
    const candidates = capturedCandidates || (typeof document === "undefined"
      ? []
      : [...document.querySelectorAll('meta[name="muyi-media-candidate"]')].map((node) => ({
        videoId: node.dataset.videoId || "",
        mediaUrl: node.dataset.mediaUrl || "",
        coverUrl: node.dataset.coverUrl || "",
      })));
    const selected = (candidates || []).find((item) => String(item?.videoId || "") === String(videoId || ""));
    return /^https:\/\//i.test(String(selected?.mediaUrl || "")) ? String(selected.mediaUrl) : "";
  }

  function douyinCoverUrl(videoId, capturedCandidates = null) {
    const candidates = capturedCandidates || (typeof document === "undefined"
      ? []
      : [...document.querySelectorAll('meta[name="muyi-media-candidate"]')].map((node) => ({
        videoId: node.dataset.videoId || "",
        coverUrl: node.dataset.coverUrl || "",
      })));
    const selected = (candidates || []).find((item) => String(item?.videoId || "") === String(videoId || ""));
    return /^https:\/\//i.test(String(selected?.coverUrl || "")) ? String(selected.coverUrl) : "";
  }

  function douyinAuthorName(videoId, capturedCandidates = null) {
    const candidates = capturedCandidates || (typeof document === "undefined"
      ? []
      : [...document.querySelectorAll('meta[name="muyi-media-candidate"]')].map((node) => ({
        videoId: node.dataset.videoId || "",
        authorName: node.dataset.authorName || "",
      })));
    const selected = (candidates || []).find((item) => String(item?.videoId || "") === String(videoId || ""));
    return cleanAuthor(selected?.authorName || "");
  }

  function selectDouyinVisibleCover(videoId, candidates = []) {
    const selectedId = String(videoId || "");
    if (!selectedId) return "";
    return (candidates || [])
      .filter((item) => String(item?.videoId || "") === selectedId)
      .filter((item) => /^https:\/\//i.test(String(item?.url || "")) && !item?.excluded)
      .filter((item) => {
        const width = Number(item?.width || 0);
        const height = Number(item?.height || 0);
        return Math.min(width, height) >= 80 && Math.max(width, height) >= 160 && width * height >= 15000;
      })
      .sort((left, right) => {
        const leftScore = Number(left?.priority || 0) * 1e8 + Number(left?.width || 0) * Number(left?.height || 0);
        const rightScore = Number(right?.priority || 0) * 1e8 + Number(right?.width || 0) * Number(right?.height || 0);
        return rightScore - leftScore;
      })[0]?.url || "";
  }

  function douyinVisibleCoverUrl(media, videoId) {
    if (!media || !videoId || typeof location === "undefined") return "";
    const identityScope = douyinScopeFor(media);
    if (!identityScope) return "";
    const scopeIdentity = normalizeDouyinSnapshot(douyinIdentitySnapshot(identityScope)).external_id;
    if (!scopeIdentity || String(scopeIdentity) !== String(videoId)) return "";
    const scope = douyinPlayerScope(media, identityScope);

    const candidates = [];
    const addCandidate = (node, url, priority = 0) => {
      const rect = node?.getBoundingClientRect?.();
      if (!rect || !isVisible(node)) return;
      const excluded = Boolean(node.closest?.(
        'a[href*="/user/"], [data-e2e*="avatar"], [class*="avatar" i], [aria-label*="头像"]'
      ));
      candidates.push({
        videoId: scopeIdentity,
        url: cleanText(url, 8000),
        width: rect.width,
        height: rect.height,
        priority,
        excluded,
      });
    };

    const poster = media.poster || media.getAttribute?.("poster") || "";
    if (poster) addCandidate(media, poster, 3);
    for (const image of scope.querySelectorAll?.("img[src]") || []) {
      addCandidate(image, image.currentSrc || image.src || "", 2);
    }
    const backgroundNodes = [scope, ...(scope.querySelectorAll?.("*") || [])].slice(0, 240);
    for (const node of backgroundNodes) {
      const url = backgroundImageUrl(node);
      if (url) addCandidate(node, url, 1);
    }
    return selectDouyinVisibleCover(scopeIdentity, candidates);
  }

  function visibleVideoAt(target, x, y) {
    let current = target;
    for (let depth = 0; current && depth < 9; depth += 1, current = current.parentElement) {
      const videos = current.matches?.("video") ? [current] : [...(current.querySelectorAll?.("video") || [])];
      const match = videos.find((video) => {
        const rect = video.getBoundingClientRect();
        return isVisible(video) && rect.width > 40 && rect.height > 40 && x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
      });
      if (match) return match;
    }
    return null;
  }

  function visibleMediaAt(target, x, y) {
    const video = visibleVideoAt(target, x, y);
    if (video) return video;
    let current = target;
    for (let depth = 0; current && depth < 9; depth += 1, current = current.parentElement) {
      const images = current.matches?.("img[src]") ? [current] : [...(current.querySelectorAll?.("img[src]") || [])];
      const match = images.find((image) => {
        const rect = image.getBoundingClientRect();
        const source = image.currentSrc || image.src || "";
        return isVisible(image) && rect.width > 40 && rect.height > 40 && /^https?:/i.test(source) &&
          x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
      });
      if (match) return match;
      const rect = current.getBoundingClientRect?.();
      if (rect && isVisible(current) && rect.width > 40 && rect.height > 40 && backgroundImageUrl(current) &&
        x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) return current;
    }
    return null;
  }

  function isInsidePlayer(node) {
    return Boolean(node?.closest?.(PLAYER_SELECTOR));
  }

  function douyinScopeFor(element) {
    return element?.closest?.('[id^="waterfall_item_"]')
      || element?.closest?.("#search-result-container li")
      || element?.closest?.('[data-e2e="feed-active-video"]')
      || element?.closest?.('[data-e2e="feed-item"]')
      || element?.closest?.(".leftContainer")
      || element?.parentElement
      || null;
  }

  function collectShortTexts(scope, selector, options = {}) {
    return [...(scope?.querySelectorAll?.(selector) || [])]
      .filter((node) => (!options.visibleOnly || isVisible(node)) && (!options.excludePlayer || !isInsidePlayer(node)))
      .flatMap((node) => [node.getAttribute?.("title"), node.getAttribute?.("aria-label"), node.innerText])
      .map((value) => cleanText(value, 300)).filter(Boolean).slice(0, 180);
  }

  function findDouyinAnchor(scope) {
    const selector = 'a[href*="/video/"], a[href*="modal_id="]';
    const candidates = scope?.matches?.(selector) ? [scope] : [...(scope?.querySelectorAll?.(selector) || [])];
    const byVideoId = new Map();
    for (const anchor of candidates) {
      const videoId = videoIdFor(anchor.href);
      if (videoId && !byVideoId.has(videoId)) byVideoId.set(videoId, anchor);
    }
    return byVideoId.size === 1 ? [...byVideoId.values()][0] : null;
  }

  function douyinIdentitySnapshot(scope) {
    return {
      pageUrl: location.href,
      elementId: scope?.id || "",
      feedVideoId: scope?.getAttribute?.("data-e2e-vid") || "",
      href: isDouyinFeedScope(scope) ? "" : findDouyinAnchor(scope)?.href || "",
    };
  }

  function isDouyinFeedScope(scope) {
    return Boolean(scope?.matches?.('[data-e2e="feed-active-video"], [data-e2e="feed-item"]'));
  }

  function douyinPlayerScope(media, scope) {
    if (!isDouyinFeedScope(scope)) return scope;
    const player = media?.closest?.(".playerContainer");
    // The active feed card also contains comments/related works. Never borrow
    // their images or metadata, even though they share the outer work scope.
    return player && scope.contains?.(player) ? player : media?.parentElement;
  }

  function collectIconCountTexts(scope) {
    const values = [];
    for (const icon of scope?.querySelectorAll?.("svg") || []) {
      if (isInsidePlayer(icon) || icon.closest?.('[data-e2e="user-info"]')) continue;
      let node = icon.parentElement;
      for (let depth = 0; depth < 4 && node && scope.contains(node); depth += 1, node = node.parentElement) {
        const text = cleanText(node.innerText, 80);
        if (looksLikeMetric(text) && !looksLikeDuration(text)) {
          values.push(text);
          break;
        }
        if (text.length > 80) break;
      }
    }
    return unique(values);
  }

  function douyinScopeKey(scope) {
    return normalizeDouyinSnapshot(douyinIdentitySnapshot(scope)).external_id;
  }

  function liveDouyinLikeTexts(scope, generalTexts = null) {
    const texts = generalTexts || collectShortTexts(scope, "a, span, p, div", { excludePlayer: true });
    return unique([
      // The work's like button lives inside xgplayer on detail/feed pages.
      // Excluding the entire player discards this count and exposes author totals.
      ...collectShortTexts(scope, '[data-e2e="video-player-digg"]'),
      ...collectShortTexts(scope, '[data-e2e*="like"], [data-e2e*="digg"], [class*="like"], [aria-label*="点赞"], [title*="点赞"]', { excludePlayer: true }),
      ...texts.filter((value) => !/获赞/.test(value) && /点赞\s*[:：]?\s*\d/i.test(value)),
      ...collectIconCountTexts(scope),
    ]).filter((value) => !looksLikeDuration(value));
  }

  function rememberDouyinTarget(target) {
    if (typeof location === "undefined" || !location.hostname.endsWith("douyin.com")) return;
    const scope = douyinScopeFor(target);
    if (!scope) return;
    const key = douyinScopeKey(scope);
    const values = liveDouyinLikeTexts(scope);
    if (key && values.length) douyinLikeCache.set(key, values);
  }

  function douyinSnapshot(video) {
    const scope = douyinScopeFor(video) || video.parentElement;
    const feed = isDouyinFeedScope(scope);
    const playerScope = douyinPlayerScope(video, scope);
    const textScope = feed ? playerScope?.querySelector?.('[data-e2e="video-info"]') : scope;
    const anchor = findDouyinAnchor(textScope);
    const generalTexts = collectShortTexts(textScope, "a, span, p, div, time", { excludePlayer: !feed });
    const key = douyinScopeKey(scope);
    const liveLikes = liveDouyinLikeTexts(playerScope, generalTexts);
    if (key && liveLikes.length) douyinLikeCache.set(key, liveLikes);
    const detailAuthor = douyinAuthorName(key);
    return {
      ...douyinIdentitySnapshot(scope),
      cardText: textScope?.innerText || textScope?.textContent || "",
      titleCandidates: [anchor?.getAttribute?.("title"), anchor?.getAttribute?.("aria-label"), anchor?.innerText,
        ...collectShortTexts(textScope, '[data-e2e*="desc"], [data-e2e*="title"], [class*="video-desc"], [class*="video-title"], [title], [aria-label]', { excludePlayer: !feed })],
      fallbackTitleCandidates: feed ? [] : [
        document.querySelector('meta[property="og:title"]')?.content,
        document.querySelector('meta[property="og:description"]')?.content,
        document.querySelector('meta[name="description"]')?.content,
        document.title,
      ],
      authorTexts: [detailAuthor, ...collectShortTexts(textScope, '[data-e2e="feed-video-nickname"], [data-e2e*="video-author"], [data-e2e*="author-name"], [class*="author-name"], [class*="nickname"], a[href*="/user/"]', { excludePlayer: !feed })],
      likeTexts: liveLikes.length ? liveLikes : douyinLikeCache.get(key) || [],
      metaTexts: generalTexts,
    };
  }

  function contextFor(media) {
    const tweet = media?.closest?.('article[data-testid="tweet"]');
    if (tweet) return tweet;
    let best = media.parentElement || media;
    let current = best;
    const selector = mediaKindFor(media) === "image" ? "img[src]" : "video";
    for (let depth = 0; current?.parentElement && depth < 8; depth += 1) {
      current = current.parentElement;
      const rect = current.getBoundingClientRect();
      const visibleMedia = [...current.querySelectorAll(selector)].filter(isVisible);
      if (visibleMedia.length !== 1) break;
      if (rect.width <= innerWidth * 1.15 && rect.height <= innerHeight * 1.5) best = current;
    }
    return best;
  }

  function normalizeXStatusUrl(value) {
    try {
      const url = new URL(value, "https://x.com/");
      const host = url.hostname.toLowerCase();
      if (host !== "x.com" && host !== "www.x.com" && host !== "twitter.com" && host !== "www.twitter.com") return "";
      const match = url.pathname.match(/^\/([^/]+)\/status\/(\d{8,})/i);
      return match ? `https://x.com/${match[1]}/status/${match[2]}` : "";
    } catch (_error) {
      return "";
    }
  }

  function xAuthorHandleFor(value) {
    const normalized = normalizeXStatusUrl(value);
    const handle = normalized.match(/^https:\/\/x\.com\/([^/]+)\/status\/\d+/i)?.[1] || "";
    return handle ? `@${handle}` : "";
  }

  function preferredLink(container) {
    const tweet = container?.closest?.('article[data-testid="tweet"]');
    let current = container;
    for (let depth = 0; current && (tweet || depth < 7); depth += 1, current = current.parentElement) {
      const anchors = [...(current.querySelectorAll?.("a[href]") || [])];
      if (current.matches?.("a[href]")) anchors.unshift(current);
      const workLinks = [...new Set(anchors.map((anchor) => {
        const href = anchor.href || "";
        if (!/^https?:/.test(href)) return "";
        return normalizeXStatusUrl(href)
          || (/\/(video|note|explore|watch|shorts|pin)\//i.test(href) ? href : "");
      }).filter(Boolean))];
      if (workLinks.length === 1) return workLinks[0];
      if (workLinks.length > 1) throw new Error("当前区域包含多个作品，请打开目标作品后再点选");
      // Never leave an identified post/card and borrow a neighbor's link.
      if (current.matches?.('article, [data-testid="tweet"], section.note-item')) break;
    }
    if (tweet) throw new Error("未能识别所选推文，请稍后在同一视频上重新点选");
    if (typeof location !== "undefined" && ["x.com", "www.x.com", "twitter.com", "www.twitter.com"].includes(location.hostname)) {
      const statusUrl = normalizeXStatusUrl(location.href);
      if (statusUrl) return statusUrl;
      throw new Error("未能识别所选推文，请稍后在同一视频上重新点选");
    }
    return normalizeXStatusUrl(typeof location === "undefined" ? "" : location.href)
      || document.querySelector('meta[property="og:url"]')?.content || location.href;
  }

  function platformFor(url) {
    let host = "";
    const fallbackUrl = typeof location === "undefined" ? "https://example.invalid/" : location.href;
    try { host = new URL(url, fallbackUrl).hostname.toLowerCase(); } catch (_error) {
      host = typeof location === "undefined" ? "" : location.hostname.toLowerCase();
    }
    if (host.endsWith("douyin.com") || host.endsWith("iesdouyin.com")) return "douyin";
    if (host.endsWith("xiaohongshu.com") || host.endsWith("xhslink.com")) return "xiaohongshu";
    if (host.endsWith("bilibili.com") || host.endsWith("b23.tv")) return "bilibili";
    if (host.endsWith("x.com") || host.endsWith("twitter.com")) return "x";
    if (host.endsWith("youtube.com") || host.endsWith("youtu.be")) return "youtube";
    return host.replace(/^www\./, "").slice(0, 80) || "web";
  }

  function externalIdFor(url) {
    return String(url).match(/\/status\/(\d{8,})/i)?.[1]
      || String(url).match(/\/(?:video|explore)\/([a-zA-Z0-9]+)/i)?.[1]
      || String(url).match(/\/(BV[0-9A-Za-z]+)/)?.[1]
      || String(url).match(/[?&](?:item_id|modal_id|video_id|vid|v)=([^&#]+)/i)?.[1] || "";
  }

  function normalizePlatformWorkUrl(value) {
    const rawUrl = cleanText(value, 4000);
    const platform = platformFor(rawUrl);
    let pageUrl = rawUrl;
    let externalId = externalIdFor(rawUrl);
    let sourceIdentityVerified = false;
    if (platform === "douyin" && /^\d{8,}$/.test(externalId)) {
      pageUrl = `https://www.douyin.com/video/${externalId}`;
      sourceIdentityVerified = true;
    } else if (platform === "x") {
      const normalized = normalizeXStatusUrl(rawUrl);
      if (normalized) {
        pageUrl = normalized;
        externalId = externalIdFor(normalized);
      }
    }
    return {
      page_url: pageUrl,
      platform,
      external_id: externalId,
      source_identity_verified: sourceIdentityVerified,
    };
  }

  function genericSelection(media) {
    const context = contextFor(media);
    const identity = normalizePlatformWorkUrl(preferredLink(media));
    const candidates = collectShortTexts(context, '[data-e2e*="desc"], [data-e2e*="title"], [class*="title"], [class*="desc"], h1, h2, h3, img[alt], [aria-label]');
    const pageTitle = unique([...candidates, ...String(context.innerText || "").split(/\r?\n/),
      document.querySelector('meta[property="og:title"]')?.content,
      document.querySelector('meta[property="og:description"]')?.content,
      document.title])
      .map((text, index) => ({ text, score: titleScore(text, index) }))
      .filter((item) => item.score >= 0).sort((left, right) => right.score - left.score)[0]?.text || "";
    const authorName = collectShortTexts(context, '[data-e2e*="author"], [data-e2e*="nickname"], [class*="author-name"], [class*="nickname"], a[href*="/user/"], a[href*="/profile/"], a[href*="/space/"]')
      .map(cleanAuthor).find(Boolean) || (identity.platform === "x" ? xAuthorHandleFor(identity.page_url) : "");
    return { page_title: pageTitle, ...identity, author_name: authorName,
      like_count_text: "", published_at_text: "" };
  }

  function normalizeImageSelectionSnapshot(snapshot = {}) {
    const mediaUrl = cleanText(snapshot.mediaUrl || snapshot.media_url, 8000);
    const pageTitle = unique([
      snapshot.alt,
      snapshot.title,
      snapshot.page_title,
      ...(snapshot.titleCandidates || []),
    ]).map((text, index) => ({ text, score: titleScore(text, index) }))
      .filter((item) => item.score >= 0)
      .sort((left, right) => right.score - left.score)[0]?.text || "";
    return {
      content_kind: "image",
      page_title: pageTitle,
      page_url: cleanText(snapshot.page_url || snapshot.pageUrl, 4000),
      media_url: mediaUrl,
      platform: cleanText(snapshot.platform, 80) || platformFor(snapshot.page_url || snapshot.pageUrl || ""),
      author_name: cleanAuthor(snapshot.author_name || snapshot.authorName),
      thumbnail_url: cleanText(snapshot.thumbnailUrl, 8000) || mediaUrl,
      external_id: cleanText(snapshot.external_id || snapshot.externalId, 300),
      like_count_text: cleanText(snapshot.like_count_text || snapshot.likeCountText, 120),
      published_at_text: cleanText(snapshot.published_at_text || snapshot.publishedAtText, 160),
    };
  }

  function xiaohongshuNoteId(value) {
    try {
      const url = new URL(String(value || ""), "https://www.xiaohongshu.com/");
      if (!["https:", "http:"].includes(url.protocol)) return "";
      if (!["www.xiaohongshu.com", "xiaohongshu.com"].includes(url.hostname.toLowerCase())) return "";
      if (url.username || url.password || url.port) return "";
      return url.pathname.match(/^\/(?:explore|discovery\/item|search_result|user\/profile\/[0-9a-f]{24})\/([0-9a-f]{24})\/?$/i)?.[1].toLowerCase() || "";
    } catch (_error) { return ""; }
  }

  function xiaohongshuMediaUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.port) return "";
      if (!/^sns-video-[a-z0-9-]+\.xhscdn\.com$/i.test(url.hostname)) return "";
      // CDN 页面有时给出 HTTP；只升级传输协议，不推算路径或视频 ID。
      url.protocol = "https:";
      return url.href;
    } catch (_error) { return ""; }
  }

  function xiaohongshuWorkUrl(values, noteId) {
    if (!noteId) return "";
    // 同一卡片常同时包含无参数的隐藏链接和带访问参数的可点击链接。
    // 只比较同一笔记的完整 URL，不拼参数，也不借用邻卡的访问参数。
    return values.filter(value => xiaohongshuNoteId(value) === noteId)
      .map(value => {
        const url = new URL(value, "https://www.xiaohongshu.com/");
        const hasToken = Boolean(url.searchParams.get('xsec_token')?.trim());
        return { url: url.href, score: hasToken ? 2 + Number(Boolean(url.searchParams.get('xsec_source')?.trim())) : 0 };
      }).sort((a, b) => b.score - a.score)[0]?.url || "";
  }

  function normalizeXiaohongshuSnapshot(snapshot = {}) {
    const pageId = xiaohongshuNoteId(snapshot.pageUrl);
    const cardId = xiaohongshuNoteId(snapshot.href);
    const noteId = cardId || pageId;
    const conflict = Boolean(pageId && cardId && pageId !== cardId);
    const note = !conflict && noteId && snapshot.candidate?.noteId === noteId ? snapshot.candidate : {};
    const video = snapshot.tag === "video" || note.kind === "video" || (snapshot.videoBadge && note.kind !== "image");
    const imageUrl = cleanText(snapshot.mediaUrl, 8000);
    const directVideo = snapshot.tag === "video" ? xiaohongshuMediaUrl(snapshot.mediaUrl) : "";
    const thumbnailUrl = video
      ? cleanText(snapshot.poster || note.coverUrl || (snapshot.tag === "img" ? imageUrl : ""), 8000)
      : imageUrl;
    return {
      platform: "xiaohongshu", external_id: noteId, source_identity_verified: Boolean(noteId && !conflict),
      page_url: xiaohongshuWorkUrl([snapshot.href, snapshot.pageUrl], noteId) || cleanText(snapshot.pageUrl, 4000),
      page_title: cleanText(note.title || snapshot.title, 500),
      author_name: cleanAuthor(note.author || snapshot.author),
      like_count_text: cleanText(note.likeCount || snapshot.likes, 120),
      published_at_text: cleanText(note.publishedAt || snapshot.publishedAt, 160),
      content_kind: video ? "video" : "image",
      media_url: video ? (noteId && !conflict ? directVideo || xiaohongshuMediaUrl(note.mediaUrl) : "") : imageUrl,
      thumbnail_url: thumbnailUrl,
      thumbnail_external_id: thumbnailUrl && noteId && !conflict ? noteId : "",
    };
  }

  function xiaohongshuSelection(media) {
    const card = media.closest?.('section.note-item, [data-note-id]');
    const detail = media.closest?.('#noteContainer, .note-container, .note-detail-mask');
    const scope = card || detail || contextFor(media);
    const anchors = [...(scope?.querySelectorAll?.('a[href]') || [])];
    if (scope?.matches?.('a[href]')) anchors.unshift(scope);
    const selectedIds = [...new Set(anchors.map(a => xiaohongshuNoteId(a.href)).filter(Boolean))];
    const declaredId = String(card?.getAttribute?.('data-note-id') || '').toLowerCase();
    const cardId = /^[0-9a-f]{24}$/.test(declaredId) ? declaredId : '';
    const directHref = media.closest?.('a[href]')?.href || '';
    const selectedId = cardId || xiaohongshuNoteId(directHref)
      || (!card && detail ? xiaohongshuNoteId(location.href) : '')
      || (selectedIds.length === 1 ? selectedIds[0] : '');
    let href = xiaohongshuWorkUrl([directHref, ...anchors.map(a => a.href)], selectedId);
    const noteId = xiaohongshuNoteId(href) || (!card ? xiaohongshuNoteId(location.href) : "");
    let candidate = null;
    if (noteId) {
      document.dispatchEvent(new CustomEvent("muyi-xhs-selected-note", { detail: noteId }));
      const meta = [...document.querySelectorAll('meta[name="muyi-xhs-note"]')].find(node => node.dataset.noteId === noteId);
      try { candidate = JSON.parse(meta?.dataset.payload || "null"); } catch (_error) { /* 保持待补全。 */ }
      if (xiaohongshuNoteId(candidate?.pageUrl) === noteId) {
        href = xiaohongshuWorkUrl([candidate.pageUrl, href], noteId);
      }
      if (!candidate && xiaohongshuNoteId(document.querySelector?.('meta[property="og:url"]')?.content) === noteId) {
        const declaredVideo = document.querySelector?.('meta[property="og:video"], meta[property="og:video:url"]')?.content;
        if (xiaohongshuMediaUrl(declaredVideo)) candidate = { noteId, kind: "video", mediaUrl: declaredVideo };
      }
    }
    const uses = [...(scope?.querySelectorAll?.('svg use') || [])];
    const videoBadge = uses.some(node => /#(?:play|video)(?:[-_][\w-]+)?$/i.test(node.getAttribute('href') || node.getAttribute('xlink:href') || ""))
      || Boolean(scope?.querySelector?.('[aria-label="播放视频"], [aria-label="播放"]'));
    const tag = media.tagName?.toLowerCase?.();
    const videos = [...(scope?.querySelectorAll?.('video') || [])].filter(isVisible);
    const selectedVideo = tag === "video" ? media : (detail && !card && videos.length === 1 ? videos[0] : null);
    const snapshot = {
      pageUrl: !card || xiaohongshuNoteId(location.href) === noteId ? location.href : location.origin + '/explore',
      href, candidate, videoBadge,
      tag: selectedVideo ? "video" : tag,
      mediaUrl: selectedVideo ? mediaUrlFor(selectedVideo) : originalImageUrlFor(media),
      poster: selectedVideo?.poster || "",
      title: scope?.querySelector?.('#detail-title, .title')?.innerText || media.alt || "",
      author: scope?.querySelector?.('.author .name, .author-wrapper .name, .author-container .username')?.innerText || "",
      likes: scope?.querySelector?.('.like-wrapper .count')?.innerText || "",
    };
    return normalizeXiaohongshuSnapshot(snapshot);
  }

  function extractSelection(media) {
    if (typeof location !== "undefined" && ["www.xiaohongshu.com", "xiaohongshu.com"].includes(location.hostname)) {
      return xiaohongshuSelection(media);
    }
    const isDouyin = typeof location !== "undefined" && location.hostname.endsWith("douyin.com");
    const scope = isDouyin ? (douyinScopeFor(media) || media.parentElement) : contextFor(media);
    const result = isDouyin ? normalizeDouyinSnapshot(douyinSnapshot(media)) : genericSelection(media);
    const xPoster = result.platform === "x" ? xVideoPosterUrl(media) : "";
    if (mediaKindFor(media) === "image" && !xPoster) {
      return normalizeImageSelectionSnapshot({
        ...result,
        mediaUrl: originalImageUrlFor(media),
        thumbnailUrl: mediaUrlFor(media),
        alt: media.alt,
        title: media.title || media.getAttribute?.("aria-label"),
        titleCandidates: [scope?.querySelector?.("figcaption")?.innerText, scope?.getAttribute?.("aria-label")],
      });
    }
    const selectedMediaUrl = result.platform === "x"
      ? (xMediaStreamUrl(media) || (mediaKindFor(media) === "video" ? mediaUrlFor(media) : ""))
      : result.platform === "douyin"
        ? douyinMediaStreamUrl(media, result.external_id)
        : mediaUrlFor(media);
    const image = scope?.querySelector?.("img[src]");
    const selectedThumbnailUrl = result.platform === "douyin"
      ? (douyinVisibleCoverUrl(media, result.external_id) || douyinCoverUrl(result.external_id))
      : xPoster || media.poster || image?.currentSrc || image?.src || document.querySelector('meta[property="og:image"]')?.content || "";
    return { ...result, content_kind: "video", media_url: selectedMediaUrl,
      thumbnail_url: selectedThumbnailUrl,
      thumbnail_external_id: result.platform === "douyin" && selectedThumbnailUrl ? result.external_id : "" };
  }

  function completeness(payload = {}) {
    const metadata = [payload.page_title, payload.author_name, payload.like_count_text, payload.published_at_text, payload.external_id].filter(Boolean).length;
    return metadata + (/^https?:\/\//i.test(payload.media_url || "") ? 1 : 0);
  }

  function captureNeedsReview(data = {}) {
    if (data.source_warning) return true;
    const adapter = data?.adapter;
    if (adapter?.contract_version === "muyi.capture-adapter.v1") {
      return adapter.outcome === "needs_review" || adapter.artifact_state === "link_pending";
    }
    return data?.status === "capture_pending";
  }

  async function extractBestSelection(media) {
    let best = null;
    let observedIdentity = "";
    for (const delayMs of [0, 200, 350, 500]) {
      if (delayMs) await new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
      if (media.isConnected === false) throw new Error("选中的素材已离开页面，请重新点选");
      const current = extractSelection(media);
      const identity = current.external_id ? `${current.platform}:${current.external_id}` : "";
      if (observedIdentity && identity !== observedIdentity) {
        throw new Error("读取期间作品发生变化，请重新点选当前素材");
      }
      if (identity && !observedIdentity) {
        observedIdentity = identity;
        // An unbound sample must not outrank the first identified work.
        best = null;
      }
      if (best?.platform === "xiaohongshu" && best.external_id === current.external_id) {
        current.page_url = xiaohongshuWorkUrl([current.page_url, best.page_url], current.external_id);
        best.page_url = current.page_url;
      }
      if (!best || completeness(current) > completeness(best)) best = current;
      // Recheck even a complete first sample after the page has had time to update.
      if (delayMs && completeness(best) >= 6) break;
    }
    return best || extractSelection(media);
  }

  if (typeof document !== "undefined" && typeof location !== "undefined" && location.hostname.endsWith("douyin.com")) {
    globalThis.setTimeout(() => {
      document.querySelectorAll('[id^="waterfall_item_"], #search-result-container li')
        .forEach((card) => rememberDouyinTarget(card));
    }, 400);
  }

  globalThis.__muyiVideoExtractor = { captureNeedsReview, cleanText, completeness, douyinAuthorName, douyinCoverUrl, douyinMediaStreamUrl, douyinVisibleCoverUrl, externalIdFor, extractBestSelection, extractSelection, mediaKindFor, mediaUrlFor, originalImageUrlFor, normalizeDouyinSnapshot, normalizeImageSelectionSnapshot, normalizePlatformWorkUrl, normalizeXStatusUrl, normalizeXiaohongshuSnapshot, xiaohongshuNoteId, xiaohongshuMediaUrl, platformFor, preferredLink, rememberDouyinTarget, selectDouyinVisibleCover, visibleMediaAt, visibleVideoAt, xAuthorHandleFor, xVideoPosterUrl, xMediaStreamUrl };
})();
