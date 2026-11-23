// Explanation contract: docs/EXPLAIN.md
export const ASSET_LIFECYCLE_STAGES = Object.freeze([
  { id: "needs_review", label: "待确认" },
  { id: "source", label: "原始素材" },
  { id: "process", label: "工程过程" },
  { id: "candidate", label: "成片候选" },
  { id: "approved", label: "正品" },
  { id: "cleanup", label: "待清理" },
]);

export function assetLifecycleStageLabel(stage) {
  return ASSET_LIFECYCLE_STAGES.find((item) => item.id === stage)?.label || "待确认";
}

export function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const number = bytes / 1024 ** index;
  return `${Number(number.toFixed(number >= 10 || index === 0 ? 0 : 1))} ${units[index]}`;
}

export function formatDuration(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  const seconds = Math.max(0, Math.round(Number(value)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function buildAssetQuery(filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== false && value !== null && value !== undefined) {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

export function filename(path) {
  const original = String(path || "").split("/").pop();
  const stem = original.replace(/\.[^.]+$/, "").trim();
  const opaqueId = stem.slice(0, 6) || "未知";
  let cleaned = stem
    .replace(/^(?:[0-9a-f]{32}-)+/i, "")
    .replace(/^\d{3}[-_]\d{6}[-_]/, "")
    .replaceAll("_", "-")
    .replaceAll("Codx", "Codex")
    .replace(/-{2,}/g, "-")
    .replace(/^[ ._-]+|[ ._-]+$/g, "");
  if (!cleaned || /^[0-9a-f]{16,}$/i.test(cleaned) || /^\d{1,2}月\d{1,2}日(?:\s*\(\d+\))?$/.test(cleaned)) {
    const extension = original.split(".").pop()?.toLowerCase();
    const kind = ["jpg", "jpeg", "png", "webp", "gif", "heic"].includes(extension)
      ? "图片"
      : ["mp3", "wav", "m4a", "aac", "flac"].includes(extension) ? "音频" : "视频";
    cleaned = `待命名${kind} · ${opaqueId}`;
  }
  return cleaned;
}

export function resetPageScroll(target = globalThis) {
  target.scrollTo(0, 0);
}

export function clampMediaTime(value, duration) {
  const requested = Number(value);
  const total = Number(duration);
  if (!Number.isFinite(requested) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.min(Math.max(requested, 0), total);
}

export function mergeAssetPages(current, next) {
  const seen = new Set(current.map((item) => item.id));
  return [...current, ...next.filter((item) => !seen.has(item.id))];
}

export function shouldLoadThumbnail(asset) {
  return !asset?.is_missing;
}

export function assetPreviewRatio(asset) {
  const width = Number(asset?.width);
  const height = Number(asset?.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return "16 / 10";
  }
  return `${width} / ${height}`;
}

export function unifiedNavigationActive(view, locationKind) {
  if (view === "home") return "home";
  if (view === "captures") return "captures";
  if (view === "content") return "content";
  if (view === "obsidian") return "obsidian";
  if (view === "settings") return "settings";
  if (view === "assets" && locationKind === "favorites") return "favorites";
  return "assets";
}

export function comfortableTypographyVars() {
  return {
    "--font-page-title": "28px",
    "--font-card-title": "16px",
    "--font-body": "14px",
    "--font-meta": "13px",
    "--font-support": "12px",
    "--nav-row-height": "44px",
    "--filter-height": "46px",
  };
}

export function normalizeFavoriteTab(value) {
  return value === "captures" ? "captures" : "assets";
}

// Calendar ranges use the browser's local timezone; the end is exclusive.
export function captureDateRange(filters = {}, now = new Date()) {
  const mode = filters.intake_time;
  if (!mode) return {};
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  if (mode === "custom") {
    const range = {};
    if (filters.intake_start) range.created_from = new Date(`${filters.intake_start}T00:00:00`).getTime() / 1000;
    if (filters.intake_end) {
      const last = new Date(`${filters.intake_end}T00:00:00`);
      last.setDate(last.getDate() + 1);
      range.created_before = last.getTime() / 1000;
    }
    return range;
  }
  if (mode === "yesterday") {
    end.setTime(start.getTime());
    start.setDate(start.getDate() - 1);
  } else if (mode === "7d" || mode === "30d") {
    start.setDate(start.getDate() - (mode === "7d" ? 6 : 29));
  }
  return { created_from: start.getTime() / 1000, created_before: end.getTime() / 1000 };
}

export function captureRequestFilters(filters = {}, { favoriteLinks = false } = {}) {
  return {
    ...filters,
    ...captureDateRange(filters),
    favorite: favoriteLinks ? true : Boolean(filters.favorite),
  };
}

export function capturePageAfterFavoriteChange({
  favoriteFiltered = false,
  nextFavorite = false,
  currentPage = 1,
  visibleCount = 0,
} = {}) {
  const page = Math.max(1, Math.floor(Number(currentPage) || 1));
  if (favoriteFiltered && !nextFavorite && Number(visibleCount) <= 1) {
    return Math.max(1, page - 1);
  }
  return page;
}

export function resolveSmartCategoriesOpen(storedValue, locationKind) {
  if (["category", "candidates"].includes(locationKind)) return true;
  return storedValue === "true";
}

export function smartCategoryHeading(categories = [], candidateCount = 0, location = {}) {
  if (location?.kind === "category") {
    const selected = categories.find((item) => item?.name === location.category);
    return { label: String(location.category || "智能分类"), count: Number(selected?.count || 0) };
  }
  if (location?.kind === "candidates") {
    return { label: "AI 候选待确认", count: Number(candidateCount || 0) };
  }
  return {
    label: "智能分类",
    count: categories.reduce((sum, item) => sum + Number(item?.count || 0), 0),
  };
}

export function latestScanSummary(scans = []) {
  const latest = [...scans].sort((left, right) => (
    Number(right?.created_at || right?.started_at || 0) - Number(left?.created_at || left?.started_at || 0)
  ))[0] || null;
  if (!latest) return null;
  const errors = Array.isArray(latest.enumeration_errors) ? latest.enumeration_errors : [];
  return {
    ...latest,
    enumeration_errors: errors,
    errorCount: errors.length,
    hasPermissionError: errors.some((item) => item?.status === "permission_required"),
    proposedMissing: Number(latest.proposed_missing || 0),
  };
}

export function latestScanBatchSummary(scans = []) {
  const ordered = [...scans].sort((left, right) => (
    Number(right?.started_at || right?.created_at || 0) - Number(left?.started_at || left?.created_at || 0)
  ));
  const newest = ordered[0];
  if (!newest) return null;
  const batchId = newest.batch_id || newest.id;
  const batchScans = ordered
    .filter((scan) => (scan.batch_id || scan.id) === batchId)
    .sort((left, right) => Number(left?.started_at || 0) - Number(right?.started_at || 0))
    .map((scan) => {
      const errors = Array.isArray(scan.enumeration_errors) ? scan.enumeration_errors : [];
      const candidates = Array.isArray(scan.missing_candidates) ? scan.missing_candidates : [];
      return {
        ...scan,
        sourceName: String(scan.source_name || "未命名来源"),
        enumeration_errors: errors,
        missing_candidates: candidates,
        errorCount: errors.length,
        proposedMissing: Number(scan.proposed_missing || 0),
      };
    });
  return {
    batchId,
    scans: batchScans,
    reviewScans: batchScans.filter((scan) => scan.commit_status === "review_required"),
    hasPermissionError: batchScans.some((scan) => (
      scan.enumeration_errors.some((item) => item?.status === "permission_required")
    )),
    errorCount: batchScans.reduce((sum, scan) => sum + scan.errorCount, 0),
    proposedMissing: batchScans.reduce((sum, scan) => sum + scan.proposedMissing, 0),
  };
}

export function adaptiveWaterfallColumns(itemCount) {
  const count = Math.max(0, Number(itemCount) || 0);
  return Math.min(6, Math.max(1, Math.ceil(Math.sqrt(count))));
}

function invalidScrapedLabel(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return true;
  if (/^\d{1,2}:\d{2}(?::\d{2})?$/.test(text)) return true;
  if (/^[\d.,]+\s*(?:万|亿|[kKmMwW])?$/.test(text)) return true;
  return /^(?:Tag\s*[:：]\s*)?(?:置顶|广告|直播|搜索|综合|视频|用户|经验|商品|Embedded video)$/i.test(text);
}

export function captureDisplayTitle(capture) {
  const title = String(capture?.page_title || "").replace(/\s+/g, " ").trim();
  if (!invalidScrapedLabel(title)) return title;
  const author = String(capture?.author_name || "")
    .replace(/^作者\s*[:：]\s*/, "")
    .replace(/^@/, "")
    .trim();
  return invalidScrapedLabel(author)
    ? `未命名${captureKindLabel(capture)}`
    : `${author}的${captureKindLabel(capture)}`;
}

export function captureKindLabel(capture) {
  return capture?.content_kind === "image" ? "图片" : "视频";
}

export function captureSourceWarning(capture) {
  if (capture?.platform !== "xiaohongshu") return "";
  try {
    const url = new URL(capture.page_url);
    if (/^https?:$/.test(url.protocol) && !url.username && !url.password
      && ['www.xiaohongshu.com', 'xiaohongshu.com'].includes(url.hostname)
      && /^\/(?:explore|discovery\/item|search_result|user\/profile\/[0-9a-f]{24})\/[0-9a-f]{24}\/?$/i.test(url.pathname)) {
      return url.searchParams.get('xsec_token')?.trim()
        ? ""
        : "原笔记链接缺少访问参数，可能无法打开；请从可正常浏览的笔记详情重新采集。";
    }
  } catch (_error) { /* 旧收藏保留原样，只提示补全。 */ }
  return "原笔记地址待核对，请从可正常浏览的笔记详情重新采集。";
}

export function captureWorkPageUrl(capture) {
  const raw = String(capture?.page_url || "").trim();
  if (!/^https?:\/\//i.test(raw)) return "";
  if (/作品\s*ID\s*不匹配/i.test(String(capture?.failure_reason || ""))) return "";
  if (capture?.platform !== "douyin" || capture?.content_kind !== "video") return raw;
  const externalId = String(capture?.external_id || "").trim();
  if (!/^\d{8,}$/.test(externalId)) return "";
  try {
    const parsed = new URL(raw);
    if (parsed.hostname.toLowerCase() !== "www.douyin.com") return "";
    if (parsed.pathname !== `/video/${externalId}`) return "";
    return `https://www.douyin.com/video/${externalId}`;
  } catch (_error) {
    return "";
  }
}

function savedCaptureImageUrl(capture) {
  return capture?.content_kind === "image" && capture.status === "downloaded"
    && capture.target_path && /^[0-9a-f]{32}$/i.test(capture.id)
    ? `/api/captures/${capture.id}/media` : "";
}

export function captureThumbnailUrl(capture) {
  const localImage = savedCaptureImageUrl(capture);
  if (localImage) return localImage;
  const captureId = String(capture?.id || "").trim();
  const status = String(capture?.thumbnail_status || "").trim();
  const remote = String(capture?.thumbnail_url || "").trim();
  if (["source_cached", "generated"].includes(status) && /^[0-9a-f]{32}$/i.test(captureId)) {
    return `/api/captures/${captureId}/thumbnail`;
  }
  if (capture?.platform === "xiaohongshu" && capture?.content_kind === "image") return "";
  if (status === "verified_remote" && /^https?:\/\//i.test(remote)) return remote;
  if (capture?.content_kind === "image" && /^https?:\/\//i.test(remote)) return remote;
  if (capture?.platform !== "douyin" && !status && /^https?:\/\//i.test(remote)) return remote;
  return "";
}

export function nextCaptureCategories(current = [], category, checked) {
  const cleanCategory = String(category || "").trim();
  const values = [...new Set((current || []).map((item) => String(item || "").trim()).filter(Boolean))];
  if (!cleanCategory) return values;
  if (!checked) return values.filter((item) => item !== cleanCategory);
  if (cleanCategory === "待分类") return ["待分类"];
  return [...values.filter((item) => item !== "待分类" && item !== cleanCategory), cleanCategory];
}

export function capturePreviewUrl(capture) {
  const localImage = savedCaptureImageUrl(capture);
  if (localImage) return localImage;
  if (capture?.platform === "xiaohongshu" && capture?.content_kind === "image") {
    return captureThumbnailUrl(capture);
  }
  const original = String(capture?.media_url || "").trim();
  const thumbnail = String(capture?.thumbnail_url || "").trim();
  const candidate = capture?.content_kind === "image" ? original || thumbnail : original;
  const captureId = String(capture?.id || "").trim();
  if (capture?.content_kind === "video" && /^[0-9a-f]{32}$/i.test(captureId) && /^https:\/\//i.test(candidate)) {
    try {
      const parsed = new URL(candidate);
      const xMp4 = capture?.platform === "x"
        && parsed.hostname.toLowerCase() === "video.twimg.com"
        && parsed.pathname.toLowerCase().endsWith(".mp4");
      const xhsVideo = capture?.platform === "xiaohongshu"
        && /^sns-video-[a-z0-9-]+\.xhscdn\.com$/i.test(parsed.hostname)
        && !parsed.username && !parsed.password && !parsed.port;
      if (xMp4 || capture?.platform === "douyin" || xhsVideo) return `/api/captures/${captureId}/media`;
      if (capture?.platform === "xiaohongshu") return "";
    } catch (_error) {
      return "";
    }
  }
  return /^https?:\/\//i.test(candidate) ? candidate : "";
}

export function captureAudioPreviewUrl(capture) {
  const captureId = String(capture?.id || "").trim();
  const audioUrl = String(capture?.audio_url || "").trim();
  if (
    capture?.platform === "douyin"
    && capture?.content_kind === "video"
    && /^[0-9a-f]{32}$/i.test(captureId)
    && /^https:\/\//i.test(audioUrl)
  ) {
    return `/api/captures/${captureId}/audio`;
  }
  return "";
}

const CAPTURE_PREVIEW_PRESENTATIONS = Object.freeze({
  ready: Object.freeze({ label: "可预览", tone: "ready", canRetry: false }),
  needs_activation: Object.freeze({ label: "预览待激活", tone: "pending", canRetry: true }),
  resolving: Object.freeze({ label: "正在后台准备预览…", tone: "working", canRetry: false }),
  needs_login: Object.freeze({ label: "需登录", tone: "attention", canRetry: true }),
  unavailable: Object.freeze({ label: "暂不可用", tone: "unavailable", canRetry: false }),
});

export function capturePreviewPresentation(capture, previewState) {
  if (capture?.platform === "xiaohongshu" && capture?.content_kind === "image") {
    if (capture?.thumbnail_status === "failed") {
      return { label: "封面加载失败", tone: "attention", canRetry: true };
    }
    if (!["source_cached", "generated"].includes(capture?.thumbnail_status)) {
      return { label: "封面待缓存", tone: "pending", canRetry: true };
    }
  }
  const requestedState = typeof previewState === "string"
    ? previewState
    : String(previewState?.state || capture?.media_refresh_status || "");
  const isDouyinVideo = ["douyin", "xiaohongshu"].includes(capture?.platform) && capture?.content_kind === "video";
  const state = isDouyinVideo
    ? requestedState || "needs_activation"
    : (capturePreviewUrl(capture) ? "ready" : "unavailable");
  const presentation = CAPTURE_PREVIEW_PRESENTATIONS[state]
    || CAPTURE_PREVIEW_PRESENTATIONS.needs_activation;
  return { ...presentation };
}

function capturePreviewStateName(capture, previewState) {
  return typeof previewState === "string"
    ? previewState
    : String(previewState?.state || capture?.media_refresh_status || "");
}

export function captureCanUseExistingDouyinPreview(capture) {
  return capture?.platform === "douyin"
    && capture?.content_kind === "video"
    && capture?.media_refresh_status === "ready"
    && /^https:\/\//i.test(String(capture?.media_url || "").trim());
}

export function capturePreviewMaintenanceAction(capture, previewState) {
  if (!["douyin", "xiaohongshu"].includes(capture?.platform) || capture?.content_kind !== "video") {
    return { visible: false, disabled: true, label: "加载预览" };
  }
  const state = capturePreviewStateName(capture, previewState) || "needs_activation";
  if (state === "resolving") {
    return { visible: true, disabled: true, label: "正在后台加载预览…" };
  }
  if (state === "unavailable") {
    return { visible: true, disabled: false, label: "重新加载预览" };
  }
  return {
    visible: true,
    disabled: false,
    label: state === "ready" ? "重新加载预览" : "加载预览",
  };
}

export function captureCanRefreshThumbnail(capture, previewState) {
  if (capture?.platform === "xiaohongshu" && capture?.content_kind === "image") {
    return /^https?:\/\//i.test(String(capture?.thumbnail_url || ""));
  }
  if (capture?.content_kind !== "video") return false;
  if (["verified_remote", "source_cached", "generated"].includes(capture?.thumbnail_status)) return false;
  if (/^https?:\/\//i.test(String(capture?.media_url || "").trim())) return true;
  return capture?.platform === "douyin"
    && capturePreviewStateName(capture, previewState) === "ready";
}

export function captureCanAutoRepairThumbnail(capture) {
  const captureId = String(capture?.id || "").trim();
  if (capture?.platform !== "xiaohongshu" || !["video", "image"].includes(capture?.content_kind)) return false;
  const eligibleStates = capture?.content_kind === "image" ? ["unverified", "verified_remote"] : ["verified_remote", "generated"];
  if (!eligibleStates.includes(capture?.thumbnail_status)
      || !/^[0-9a-f]{32}$/i.test(captureId)) return false;
  try {
    const thumbnail = new URL(String(capture?.thumbnail_url || ""));
    return ["http:", "https:"].includes(thumbnail.protocol)
      && !thumbnail.username && !thumbnail.password && !thumbnail.port
      && /^sns-(?:webpic|img)-[a-z0-9-]+\.xhscdn\.com$/i.test(thumbnail.hostname);
  } catch (_error) {
    return false;
  }
}

export function captureThumbnailRefreshSuccessMessage(capture) {
  if (capture?.platform === "xiaohongshu" && capture?.content_kind === "image") {
    return "已缓存这张图片的预览封面";
  }
  return capture?.platform === "xiaohongshu"
    ? "已缓存这条小红书视频的原封面，没有保存完整视频"
    : "已从这条视频生成封面，没有保存完整视频";
}

export function createCapturePreviewSessionController({
  clock = () => Date.now(),
  setTimer = (callback, delay) => setTimeout(callback, delay),
  clearTimer = (timer) => clearTimeout(timer),
  timeoutMs = 125000,
} = {}) {
  let captureId = "";
  let actionId = 0;
  let deadlineTimer = null;
  let autoRetried = false;

  const currentToken = () => ({
    captureId,
    actionId,
    key: `${captureId || "idle"}:${actionId}`,
  });

  const isCurrent = (token) => (
    Boolean(captureId)
    && String(token?.captureId || "") === captureId
    && Number(token?.actionId) === actionId
  );

  const clearDeadline = (token = null) => {
    if (token && !isCurrent(token)) return false;
    if (deadlineTimer !== null) {
      clearTimer(deadlineTimer);
      deadlineTimer = null;
    }
    return true;
  };

  const beginGeneration = (nextCaptureId, { resetAutoRetry = false } = {}) => {
    clearDeadline();
    captureId = String(nextCaptureId || "");
    actionId += 1;
    if (resetAutoRetry) autoRetried = false;
    return currentToken();
  };

  return {
    open(nextCaptureId) {
      return beginGeneration(nextCaptureId, { resetAutoRetry: true });
    },
    manualRetry(expectedCaptureId) {
      if (!captureId || String(expectedCaptureId || "") !== captureId) return null;
      return { force: true, token: beginGeneration(captureId) };
    },
    retryFromVideoError(payload) {
      if (!isCurrent(payload) || autoRetried) return null;
      autoRetried = true;
      return { force: true, token: beginGeneration(captureId) };
    },
    isCurrent,
    applyIfCurrent(token, callback) {
      if (!isCurrent(token)) return false;
      callback();
      return true;
    },
    armDeadline(token, callback) {
      if (!isCurrent(token)) return false;
      clearDeadline();
      const startedAt = Number(clock());
      deadlineTimer = setTimer(() => {
        deadlineTimer = null;
        if (!isCurrent(token)) return;
        const expired = currentToken();
        actionId += 1;
        callback({
          captureId: expired.captureId,
          actionId: expired.actionId,
          elapsedMs: Math.max(0, Number(clock()) - startedAt),
        });
      }, Math.max(0, Number(timeoutMs) || 0));
      return true;
    },
    clearDeadline,
    close() {
      clearDeadline();
      captureId = "";
      actionId += 1;
      autoRetried = false;
      return currentToken();
    },
    snapshot() {
      return currentToken();
    },
  };
}

export function normalizePrimaryView(value) {
  const view = String(value || "");
  return ["home", "assets", "captures", "settings"].includes(view) ? view : "assets";
}

export async function startCapturePlayback(player, { onBlocked, fallbackDelayMs = 350 } = {}) {
  if (!player || typeof player.play !== "function") return false;
  const originalMuted = Boolean(player.muted);
  let firstAttempt;
  try {
    firstAttempt = Promise.resolve(player.play()).then(
      () => ({ ok: true, reason: null }),
      (reason) => ({ ok: false, reason }),
    );
  } catch (error) {
    firstAttempt = Promise.resolve({ ok: false, reason: error });
  }

  const waitMs = Math.max(0, Number(fallbackDelayMs) || 0);
  const firstResult = await Promise.race([
    firstAttempt,
    new Promise((resolve) => setTimeout(
      () => resolve({ ok: player.paused === false, reason: null }),
      waitMs,
    )),
  ]);
  if (firstResult.ok || player.paused === false) return true;

  player.muted = true;
  try {
    await player.play();
    return true;
  } catch (error) {
    player.muted = originalMuted;
    if (typeof onBlocked === "function") onBlocked(error || firstResult.reason);
    return false;
  }
}

export function syncCapturePreviewSound(video, audio) {
  if (!video || !audio) return false;
  audio.muted = video.muted;
  audio.volume = video.volume;
  return video.muted === false && Number(video.volume) > 0;
}

export function toggleCapturePreviewSound(video, audio) {
  if (!video || !audio) return false;
  const enabled = video.muted || Number(video.volume) <= 0;
  video.muted = !enabled;
  if (enabled && Number(video.volume) <= 0) video.volume = 1;
  syncCapturePreviewSound(video, audio);
  return enabled;
}

export function capturePreviewMode(capture) {
  const url = capturePreviewUrl(capture);
  if (!url) return "unavailable";
  if (capture?.content_kind === "image") return "image";
  try {
    return new URL(url, "http://127.0.0.1").pathname.toLowerCase().endsWith(".m3u8") ? "hls" : "direct";
  } catch (_error) {
    return "unavailable";
  }
}

export function captureNeedsRemoteRefresh(capture) {
  return ["x", "douyin"].includes(capture?.platform)
    && capture?.content_kind === "video"
    && !/^https?:\/\//i.test(String(capture?.media_url || "").trim());
}

export function captureCanRefreshRemotePreview(capture) {
  if (!["x", "douyin"].includes(capture?.platform) || capture?.content_kind !== "video") return false;
  if (capture?.status === "downloaded" && capture?.target_path) return false;
  return captureNeedsRemoteRefresh(capture) || capture?.platform === "douyin";
}

export function capturePreviewFailureMessage(capture) {
  if (capture?.status === "downloaded" && capture?.target_path) {
    return "本地已验证文件暂时无法播放，需要检查文件或播放器。";
  }
  if (capture?.platform === "xiaohongshu") {
    return "小红书预览地址已失效，正在尝试自动刷新；仍无法播放时可点“重新加载预览”。";
  }
  return "当前是外部链接预览，地址可能已失效或受来源限制；可点“重新补全预览”，这不代表本地文件丢失。";
}

export function captureLocalSaveAction(capture, { saving = false, previewState = null } = {}) {
  const image = capture?.content_kind === "image";
  if (!image && capture?.content_kind !== "video") return { visible: false };
  if (saving || capture?.status === "downloading") {
    return {
      visible: true,
      disabled: true,
      state: "saving",
      label: "正在保存…",
      description: "正在下载并校验，完成前不会写入正式文件。",
    };
  }
  if (capture?.status === "downloaded" && capture?.target_path) {
    return {
      visible: true,
      disabled: true,
      state: "saved",
      label: "已保存到本地",
      description: "后续预览优先读取本地文件，不再依赖远端地址。",
    };
  }
  if (image) {
    const hasOriginal = /^https?:\/\//i.test(String(capture.media_url || ""));
    return {
      visible: true,
      disabled: !hasOriginal,
      state: hasOriginal ? "available" : "unavailable",
      label: "保存原图",
      description: hasOriginal ? "保留网页图像的原始文件，保存后可离线查看。" : "请回到原网页重新点选图片。",
    };
  }
  const douyinPreviewReady = capture?.platform === "douyin"
    && capturePreviewStateName(capture, previewState) === "ready";
  const hasRemoteMedia = /^https:\/\//i.test(String(capture?.media_url || "").trim())
    || douyinPreviewReady;
  if (!hasRemoteMedia) {
    return {
      visible: true,
      disabled: true,
      state: "unavailable",
      label: "先补全预览地址",
      description: "取得可核验的真实媒体地址后，才能安全保存。",
    };
  }
  if (capture?.platform === "x") {
    try {
      const parsed = new URL(String(capture.media_url));
      if (parsed.hostname.toLowerCase() !== "video.twimg.com" || !parsed.pathname.toLowerCase().endsWith(".mp4")) {
        return {
          visible: true,
          disabled: true,
          state: "unavailable",
          label: "当前只有流式预览",
          description: "这条 X 视频目前是 HLS 流，补全为 MP4 后才能安全保存。",
        };
      }
    } catch (_error) {
      return {
        visible: true,
        disabled: true,
        state: "unavailable",
        label: "先补全预览地址",
        description: "取得可核验的真实媒体地址后，才能安全保存。",
      };
    }
  } else if (capture?.platform && !["douyin", "xiaohongshu"].includes(capture.platform)) {
    return {
      visible: true,
      disabled: true,
      state: "unavailable",
      label: "当前平台暂不支持本地保存",
      description: "先继续保留作品链接；当前只开放已核验的 X、抖音和小红书视频。",
    };
  }
  const retry = capture?.status === "download_failed";
  return {
    visible: true,
    disabled: false,
    state: retry ? "failed" : "available",
    label: retry ? "重新保存到本地" : "保存到本地",
    description: retry
      ? "上次没有生成正式文件，链接卡仍然保留。"
      : douyinPreviewReady
      ? "当前预览已经准备好；只有你主动点击才下载并校验。"
      : "当前只保存外部链接，预览地址可能失效；只有你主动点击才下载并校验。",
  };
}

export function captureDisplayMetadata(capture) {
  const author = String(capture?.author_name || "").replace(/^作者\s*[:：]\s*/, "").trim();
  const items = [];
  if (!invalidScrapedLabel(author)) items.push({ key: "author", value: author });
  if (capture?.like_count_text) items.push({ key: "like", value: String(capture.like_count_text).trim() });
  if (capture?.published_at_text) items.push({ key: "published", value: String(capture.published_at_text).trim() });
  return items;
}

export function duplicateCleanupSummary(keeper, copies = []) {
  const removable = copies.filter((item) => item?.id && item.id !== keeper?.id);
  return {
    copyCount: removable.length,
    reclaimableBytes: removable.reduce((sum, item) => sum + Math.max(0, Number(item.size) || 0), 0),
    keeperLabel: [keeper?.source_name, keeper?.relative_path].filter(Boolean).join(" / "),
  };
}

export function paginationModel(totalItems, requestedPage, pageSize = 48) {
  const size = Number.isFinite(Number(pageSize)) && Number(pageSize) > 0 ? Math.floor(Number(pageSize)) : 48;
  const total = Math.max(0, Number(totalItems) || 0);
  const pageCount = Math.max(1, Math.ceil(total / size));
  const page = Math.min(pageCount, Math.max(1, Math.floor(Number(requestedPage) || 1)));
  const pages = new Set([1, pageCount]);
  for (let value = page - 2; value <= page + 2; value += 1) {
    if (value > 1 && value < pageCount) pages.add(value);
  }
  if (page <= 3) {
    for (let value = 2; value <= Math.min(5, pageCount - 1); value += 1) pages.add(value);
  }
  if (page >= pageCount - 2) {
    for (let value = Math.max(2, pageCount - 4); value < pageCount; value += 1) pages.add(value);
  }
  const sorted = [...pages].sort((left, right) => left - right);
  const items = [];
  sorted.forEach((value, index) => {
    if (index && value - sorted[index - 1] > 1) {
      items.push(index === 1 ? "ellipsis-left" : "ellipsis-right");
    }
    items.push(value);
  });
  return { page, pageCount, offset: (page - 1) * size, items };
}

export function workspaceLocationKey(location = { kind: "all" }) {
  switch (location.kind) {
    case "folder":
      return `folder:${String(location.sourceId || "")}:${String(location.folder || "")}`;
    case "source":
      return `source:${String(location.sourceId || "")}`;
    case "category":
      return `category:${String(location.category || "")}`;
    case "stage":
      return `stage:${String(location.stage || "")}`;
    case "collection":
      return `collection:${String(location.collectionId || "")}`;
    case "favorites":
    case "candidates":
    case "missing":
      return location.kind;
    default:
      return "all";
  }
}

export function workspaceFilters(location = { kind: "all" }, mediaType = "video") {
  const videoOnly = { type: mediaType };
  switch (location.kind) {
    case "favorites":
      return { favorite: true, ...videoOnly, availability: "available" };
    case "category":
      return location.category
        ? { category: location.category, ...videoOnly, availability: "available" }
        : { ...videoOnly, availability: "available" };
    case "stage":
      return location.stage
        ? { lifecycle_stage: location.stage, ...videoOnly, availability: "available" }
        : { ...videoOnly, availability: "available" };
    case "candidates":
      return { status: "candidate", ...videoOnly, availability: "available" };
    case "collection":
      return location.collectionId
        ? { collection: location.collectionId, ...videoOnly, availability: "available" }
        : { ...videoOnly, availability: "available" };
    case "source":
      return location.sourceId
        ? { source: location.sourceId, folder_scope: "direct", ...videoOnly, availability: "available" }
        : { ...videoOnly, availability: "available" };
    case "folder":
      return location.sourceId && location.folder
        ? { source: location.sourceId, folder: location.folder, folder_scope: "recursive", ...videoOnly, availability: "available" }
        : { ...videoOnly, availability: "available" };
    case "missing":
      return { ...videoOnly, availability: "missing" };
    default:
      return { ...videoOnly, availability: "available" };
  }
}

export function normalizeWorkspaceLocation(value, context = {}) {
  const fallback = { kind: "all" };
  if (!value || typeof value !== "object") return fallback;
  const sourceIds = new Set(context.sourceIds || []);
  const collectionIds = new Set(context.collectionIds || []);
  const categories = new Set(context.categories || []);
  const lifecycleStages = new Set(context.lifecycleStages || []);
  if (["all", "favorites", "candidates", "missing"].includes(value.kind)) return { kind: value.kind };
  if (value.kind === "category" && categories.has(value.category)) {
    return { kind: "category", category: String(value.category) };
  }
  if (value.kind === "stage" && lifecycleStages.has(value.stage)) {
    return { kind: "stage", stage: String(value.stage) };
  }
  if (value.kind === "collection" && collectionIds.has(value.collectionId)) {
    return { kind: "collection", collectionId: String(value.collectionId) };
  }
  if (value.kind === "source" && sourceIds.has(value.sourceId)) {
    return { kind: "source", sourceId: String(value.sourceId), folder: "" };
  }
  if (value.kind === "folder" && sourceIds.has(value.sourceId)) {
    const parts = String(value.folder || "").split("/");
    if (parts.length && parts.every((part) => part && part !== "." && part !== "..")) {
      return {
        kind: "folder",
        sourceId: String(value.sourceId),
        folder: parts.join("/"),
      };
    }
  }
  return fallback;
}

export function folderKey(sourceId, folder = "") {
  return `${String(sourceId || "")}:${String(folder || "")}`;
}

export function folderAncestors(sourceId, folder = "") {
  const parts = String(folder || "").split("/").filter(Boolean);
  const keys = [folderKey(sourceId, "")];
  for (let index = 1; index < parts.length; index += 1) {
    keys.push(folderKey(sourceId, parts.slice(0, index).join("/")));
  }
  return keys;
}
