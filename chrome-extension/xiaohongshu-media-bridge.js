// Explanation contract: docs/EXPLAIN.md
(() => {
  if (globalThis.__muyiXiaohongshuBridge) return;

  function playableVideoKey(value) {
    try {
      const url = new URL(String(value || ""));
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.port) return "";
      if (!/^sns-video-[a-z0-9-]+\.xhscdn\.com$/i.test(url.hostname)) return "";
      return `${url.hostname.toLowerCase()}${url.pathname}`;
    } catch (_error) { return ""; }
  }

  function metricText(value) {
    const text = String(value ?? "").trim();
    return /^[\d.,]+\s*(?:万|亿|[kKmMwW])?$/.test(text) ? text.slice(0, 120) : "";
  }

  function publishedAtText(value) {
    const raw = String(value ?? "").trim();
    if (!/^\d{10,13}$/.test(raw)) return "";
    const numeric = Number(raw);
    const milliseconds = raw.length <= 10 ? numeric * 1000 : numeric;
    const date = new Date(milliseconds);
    if (!Number.isFinite(milliseconds) || Number.isNaN(date.getTime())
        || date.getFullYear() < 2000 || date.getFullYear() > 2100) return "";
    const pad = part => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function noteCandidate(note, expectedId, pageUrl = "", playedUrls = []) {
    if (!/^[0-9a-f]{24}$/i.test(expectedId || "") || String(note?.noteId || note?.note_id || "").toLowerCase() !== expectedId.toLowerCase()) return null;
    const kind = note.type === "video" ? "video" : note.type === "normal" ? "image" : "";
    if (!kind) return null;
    const stream = note.video?.media?.stream || {};
    const h264 = Array.isArray(stream.h264) ? stream.h264 : [];
    const streamItems = Object.values(stream).flatMap(value => Array.isArray(value) ? value : []);
    const playedKeys = new Set(playedUrls.map(playableVideoKey).filter(Boolean));
    const playedMedia = streamItems.map(item => item?.masterUrl || item?.master_url || "")
      .find(url => playedKeys.has(playableVideoKey(url))) || "";
    const legacyH264 = h264.map(item => item?.masterUrl || item?.master_url || "")
      .find(url => /^https?:\/\//i.test(url)) || "";
    const mediaUrl = kind === "video" ? playedMedia || legacyH264 : "";
    const firstImage = note.imageList?.[0] || {};
    return {
      noteId: expectedId.toLowerCase(), kind, mediaUrl,
      title: String(note.title || note.displayTitle || note.desc || "").slice(0, 500),
      author: String(note.user?.nickname || note.user?.nickName || "").slice(0, 100),
      likeCount: metricText(note.interactInfo?.likedCount ?? note.interact_info?.liked_count),
      publishedAt: publishedAtText(note.time ?? note.publishTime ?? note.publish_time),
      coverUrl: String(firstImage.urlDefault || firstImage.url || note.cover?.urlDefault || note.cover?.url || "").slice(0, 8000),
      pageUrl: String(pageUrl || "").slice(0, 4000),
    };
  }

  function unrefArray(value) {
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.value)) return value.value;
    if (Array.isArray(value?._value)) return value._value;
    return [];
  }

  function feedPageUrl(item, expectedId) {
    if (String(item?.id || "").toLowerCase() !== expectedId) return "";
    const token = String(item?.xsecToken || "").trim();
    if (!token || token.length > 2000 || /[\u0000-\u001f\u007f]/.test(token)) return "";
    const pathname = location.pathname || new URL(location.href).pathname;
    const source = pathname.startsWith('/search_result')
      ? 'pc_search'
      : pathname.startsWith('/user/profile') ? 'pc_user' : 'pc_feed';
    const url = new URL(`/explore/${expectedId}`, location.origin);
    url.searchParams.set('xsec_token', token);
    url.searchParams.set('xsec_source', source);
    return url.href;
  }

  function selectedFeedCandidate(expectedId) {
    const state = globalThis.__INITIAL_STATE__ || {};
    const collections = [state.feed?.feeds, state.search?.feeds, state.red?.feeds];
    for (const collection of collections) {
      const item = unrefArray(collection).find(entry => String(entry?.id || "").toLowerCase() === expectedId);
      if (!item?.noteCard) continue;
      const candidate = noteCandidate({ ...item.noteCard, noteId: item.id }, expectedId, feedPageUrl(item, expectedId));
      if (candidate) return candidate;
    }
    return null;
  }

  function playedVideoUrls(expectedId) {
    if (typeof location === "undefined" || typeof performance === "undefined") return [];
    const pageId = location.pathname.match(/^\/(?:explore|discovery\/item|search_result|user\/profile\/[0-9a-f]{24})\/([0-9a-f]{24})\/?$/i)?.[1]?.toLowerCase() || "";
    if (pageId !== expectedId) return [];
    return performance.getEntriesByType?.('resource')
      ?.map(entry => String(entry?.name || ""))
      .filter(value => playableVideoKey(value)) || [];
  }

  // 只在主动点选时读取这个 ID 的笔记；不监听请求，不遍历信息流，不读登录凭据。
  function onSelectedNote(event) {
    const id = typeof event.detail === "string" ? event.detail.toLowerCase() : "";
    if (!/^[0-9a-f]{24}$/.test(id)) return;
    const nodes = [...document.querySelectorAll('meta[name="muyi-xhs-note"]')];
    let meta = nodes.find(node => node.dataset.noteId === id);
    if (meta) meta.remove(); // 清掉上一次结果，防止页面切换后继续用旧票据。
    const note = globalThis.__INITIAL_STATE__?.note?.noteDetailMap?.[id]?.note;
    const feedCandidate = selectedFeedCandidate(id);
    const detailCandidate = noteCandidate(note, id, feedCandidate?.pageUrl, playedVideoUrls(id));
    const candidate = detailCandidate || feedCandidate;
    if (!candidate || !document.documentElement) return;
    meta = document.createElement('meta');
    meta.name = 'muyi-xhs-note';
    meta.dataset.noteId = id;
    meta.dataset.payload = JSON.stringify(candidate);
    document.documentElement.appendChild(meta);
    for (const old of nodes.filter(node => node !== meta).slice(0, Math.max(0, nodes.length - 15))) old.remove();
  }

  if (typeof document !== "undefined") document.addEventListener('muyi-xhs-selected-note', onSelectedNote);
  globalThis.__muyiXiaohongshuBridge = { noteCandidate, selectedFeedCandidate };
})();
