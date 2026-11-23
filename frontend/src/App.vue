<script setup>
// Explanation contract: docs/EXPLAIN.md
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { api } from "./api.js";
import { useCapturePreview } from "./composables/useCapturePreview.js";
import { useCaptureActions } from "./composables/useCaptureActions.js";
import { useCapturePurposes } from "./composables/useCapturePurposes.js";
import AssetDetails from "./components/AssetDetails.vue";
import CaptureCard from "./components/CaptureCard.vue";
import CaptureEditor from "./components/CaptureEditor.vue";
import MaterialWorkspace from "./components/MaterialWorkspace.vue";
import {
  ASSET_LIFECYCLE_STAGES,
  adaptiveWaterfallColumns,
  assetLifecycleStageLabel,
  assetPreviewRatio,
  buildAssetQuery,
  comfortableTypographyVars,
  capturePageAfterFavoriteChange,
  captureRequestFilters,
  captureDateRange,
  duplicateCleanupSummary,
  filename,
  folderAncestors,
  folderKey,
  formatBytes,
  formatDuration,
  latestScanBatchSummary,
  normalizeFavoriteTab,
  normalizePrimaryView,
  normalizeWorkspaceLocation,
  paginationModel,
  resetPageScroll,
  shouldLoadThumbnail,
  unifiedNavigationActive,
  workspaceFilters,
  workspaceLocationKey,
} from "./utils.js";

const loading = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const view = ref("assets");
const categories = ref([]);
const captureCategories = ref([]);
const sources = ref([]);
const collections = ref([]);
const scans = ref([]);
const scanQueue = ref({ status: "idle", active: 0 });
const assets = ref([]);
const totalAssets = ref(0);
const hiddenAssets = ref(0);
const pageLoading = ref(false);
const currentPage = ref(1);
const pagesByLocation = ref({});
const selected = ref(null);
const selectedIds = ref([]);
const captureToken = ref("");
const captures = ref([]);
const captureCount = ref(0);
const captureTotal = ref(0);
const capturePage = ref(1);
const captureLoading = ref(false);
const captureStats = ref({ platforms: {}, statuses: {}, kinds: {} });
const captureFilters = reactive({ intake_time: "", intake_start: "", intake_end: "", q: "", content_kind: "", category: "", platform: "", status: "", favorite: false });
const lifecycleStages = ref(ASSET_LIFECYCLE_STAGES.map((item) => ({ ...item, count: 0 })));
const duplicates = ref({ status: "idle", pending_assets: 0, exact_groups: 0, hidden_copies: 0 });
const duplicateCopies = ref([]);
const filters = reactive({ q: "", type: "video", category: "", collection: "", source: "", folder: "", folder_scope: "recursive", orientation: "", status: "", lifecycle_stage: "", date_from: "", date_to: "", favorite: false, dedupe: true, availability: "available" });
const editor = reactive({ display_name: "", note: "", tags: "", categories: [], collections: [], lifecycle_stage: "needs_review" });
const batchLifecycleStage = ref("");
const currentLocation = ref({ kind: "all" });
const expandedFolderKeys = ref([]);
const folderChildrenByKey = reactive({});
const folderLoadingKeys = ref([]);
const folderErrors = reactive({});
const assetViewMode = ref("grid");
const treeDrawerOpen = ref(false);
const packMenuOpen = ref(false);
const missingCount = ref(0);
const favoriteTab = ref("assets");
const standalone = ref(true);
const mediaToolsReady = ref(true);
const favoriteContext = ref(false);
const recoveryPreview = ref(null);
const privacyProgramPath = ref("");
let poller;
let listedScanId;
let filterLoadTimer;
let captureFilterTimer;
let ignoreFilterWatch = false;
let restoringWorkspaceState = false;
const ASSET_PAGE_SIZE = 48;
const CAPTURE_PAGE_SIZE = 36;
const LOCATION_STORAGE_KEY = "muyi.material-library.location.v1";
const EXPANDED_STORAGE_KEY = "muyi.material-library.expanded-folders.v1";
const VIEW_MODE_STORAGE_KEY = "muyi.material-library.view.v1";
const PAGE_STORAGE_KEY = "muyi.material-library.pages.v1";
const ACTIVE_VIEW_STORAGE_KEY = "muyi.material-library.active-view.v1";
const FAVORITE_TAB_STORAGE_KEY = "muyi.material-library.favorite-tab.v1";
const FAVORITE_CONTEXT_STORAGE_KEY = "muyi.material-library.favorite-context.v1";

const {
  selectedCapture, captureEditorView, captureEditor, capturePreviewError,
  capturePreviewState, capturePreviewGeneration, captureRepairing,
  capturePreviewHasAudio, capturePreviewSoundEnabled, openCaptureEditor,
  closeCaptureEditor, retryCapturePreview, handleCapturePreviewError,
  refreshCapturePreview, startCaptureAudioTrack, pauseCaptureAudioTrack,
  syncCaptureAudioTrack, toggleCapturePreviewSoundControl,
} = useCapturePreview({ captures, showError, showNotice });
const {
  captureSavingId, refreshCaptureThumbnail, repairCaptureThumbnailAutomatically,
  saveCaptureLocal, setCaptureCategory, updateCaptureEditorField, saveCaptureEditor,
  toggleCaptureFavorite, deleteCapture, copyCaptureLink, copyCaptureMediaLink,
} = useCaptureActions({
  captures, selectedCapture, captureEditor, closeCaptureEditor, capturePreviewError,
  captureRepairing, busy, showError, showNotice,
  onFavoriteChanged: async (updated) => {
    const favoriteFiltered = favoriteContext.value || Boolean(captureFilters.favorite);
    if (favoriteFiltered && !updated.favorite) {
      const page = capturePageAfterFavoriteChange({
        favoriteFiltered,
        nextFavorite: updated.favorite,
        currentPage: capturePage.value,
        visibleCount: captures.value.length,
      });
      await loadCaptures({ page });
    } else {
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
    }
  },
  onDeleted: async () => {
    captureCount.value = Math.max(0, captureCount.value - 1);
    await loadCaptures({ page: capturePage.value });
  },
});
const {
  capturePurposeManagerOpen, capturePurposeDraft, capturePurposeNames,
  capturePurposeReplacements, reloadCaptureCategories, createCapturePurpose,
  renameCapturePurpose, deleteCapturePurpose, openCapturePurposeManager,
} = useCapturePurposes({ captureCategories, captureFilters, captureEditor, busy, loadCaptures, showError, showNotice });

const title = computed(() => {
  if (view.value === "home") return "你的全部素材，一眼看清";
  if (favoriteContext.value) return "我的收藏";
  if (view.value === "captures") return "链接收集箱";
  if (view.value === "settings") return "素材来源与设置";
  if (currentLocation.value.kind === "favorites") return "我的收藏";
  if (currentLocation.value.kind === "missing") return "失效索引";
  if (currentLocation.value.kind === "stage") return assetLifecycleStageLabel(currentLocation.value.stage);
  if (currentLocation.value.kind === "collection") return collections.value.find((item) => item.id === currentLocation.value.collectionId)?.name || "我的素材包";
  if (currentLocation.value.kind === "category") return currentLocation.value.category;
  if (currentLocation.value.kind === "folder") return currentLocation.value.folder.split("/").filter(Boolean).pop();
  if (currentLocation.value.kind === "source") return sources.value.find((item) => item.id === currentLocation.value.sourceId)?.name || "当前来源";
  return "全部素材";
});
const subtitle = computed(() => {
  if (view.value === "home") return "素材默认原地保存；只有你确认清理的完全重复副本才会进入废纸篓。";
  if (favoriteContext.value) return `${captureTotal.value} 条已收藏的网页链接素材`;
  if (view.value === "captures") return `${captureTotal.value} 条网页素材链接，同一张图或同一条视频重复点击自动合并`;
  if (view.value === "settings") return standalone.value ? "管理本地文件夹和浏览器收集器。" : "普通管理只改索引；清理完全重复副本需要明确确认。";
  if (hiddenAssets.value) return `${totalAssets.value} 条素材，已折叠 ${hiddenAssets.value} 个内容相同的副本`;
  return `${totalAssets.value} 条素材${filters.dedupe ? "（重复项已折叠）" : ""}`;
});
const runningScan = computed(() => scans.value.find((item) => item.status === "running"));
const completedScanId = computed(() => scans.value.find((item) => item.status === "completed")?.id);
const latestScanBatch = computed(() => latestScanBatchSummary(scans.value));
const currentSource = computed(() => sources.value.find((item) => item.id === filters.source));
const isPhysicalLocation = computed(() => ["source", "folder"].includes(currentLocation.value.kind));
const currentFolderKey = computed(() => isPhysicalLocation.value ? folderKey(filters.source, filters.folder) : "");
const childFolders = computed(() => (
  currentFolderKey.value && !filters.folder
    ? (folderChildrenByKey[currentFolderKey.value] || [])
    : []
));

const breadcrumbs = computed(() => {
  if (!isPhysicalLocation.value) return [{ label: title.value, location: currentLocation.value }];
  const items = [{
    label: currentSource.value?.name || "来源",
    location: { kind: "source", sourceId: filters.source, folder: "" },
  }];
  const parts = filters.folder.split("/").filter(Boolean);
  parts.forEach((part, index) => items.push({
    label: part,
    location: { kind: "folder", sourceId: filters.source, folder: parts.slice(0, index + 1).join("/") },
  }));
  return items;
});
const confirmedCategories = (asset) => asset.categories?.filter((item) => item.status === "confirmed") || [];
const duplicateCleanup = computed(() => duplicateCleanupSummary(selected.value, duplicateCopies.value));
const pagination = computed(() => paginationModel(totalAssets.value, currentPage.value, ASSET_PAGE_SIZE));
const capturePagination = computed(() => paginationModel(captureTotal.value, capturePage.value, CAPTURE_PAGE_SIZE));
const capturePlatforms = computed(() => Object.entries(captureStats.value.platforms || {}));
const pageRangeLabel = computed(() => {
  if (!totalAssets.value) return "0 条";
  const start = pagination.value.offset + 1;
  const end = Math.min(totalAssets.value, pagination.value.offset + assets.value.length);
  return `${start}–${end} / ${totalAssets.value}`;
});
const captureRangeLabel = computed(() => {
  if (!captureTotal.value) return "0 条";
  const start = capturePagination.value.offset + 1;
  const end = Math.min(captureTotal.value, capturePagination.value.offset + captures.value.length);
  return `${start}–${end} / ${captureTotal.value}`;
});
const activeNavigation = computed(() => favoriteContext.value
  ? "favorites"
  : unifiedNavigationActive(view.value, currentLocation.value.kind));
const waterfallColumnCount = computed(() => adaptiveWaterfallColumns(assets.value.length));

function showError(reason) {
  error.value = reason?.message || String(reason);
  window.setTimeout(() => (error.value = ""), 6000);
}
function showNotice(message) {
  notice.value = message;
  window.setTimeout(() => (notice.value = ""), 3500);
}

function resetVisiblePage() {
  resetPageScroll(document.querySelector(".workspace-content") || window);
}

async function bootstrap() {
  const data = await api.get("/api/bootstrap");
  standalone.value = Boolean(data.standalone);
  const missingType = standalone.value ? "" : "&type=video";
  const missing = await api.get(`/api/assets?availability=missing${missingType}&limit=1&offset=0`);
  categories.value = data.categories;
  const lifecycleCounts = new Map((data.lifecycle_stages || []).map((item) => [item.id, Number(item.count || 0)]));
  lifecycleStages.value = ASSET_LIFECYCLE_STAGES.map((item) => ({
    ...item,
    count: lifecycleCounts.get(item.id) || 0,
  }));
  captureCategories.value = data.capture_categories || [];
  captureCategories.value.forEach((category) => {
    capturePurposeNames[category.id] = category.name;
  });
  sources.value = data.sources;
  collections.value = data.collections;
  scans.value = data.scans;
  scanQueue.value = data.scan_queue;
  captureToken.value = data.capture_token;
  mediaToolsReady.value = data.media_tools_ready !== false;
  captureCount.value = Number(data.capture_count || 0);
  duplicates.value = data.duplicates || duplicates.value;
  missingCount.value = Number(missing.total || 0);
}

function workspaceContext() {
  return {
    sourceIds: sources.value.map((item) => item.id),
    collectionIds: collections.value.map((item) => item.id),
    categories: categories.value.map((item) => item.name),
    lifecycleStages: lifecycleStages.value.map((item) => item.id),
  };
}

function readStoredJson(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch (_error) {
    return fallback;
  }
}

function persistWorkspaceState() {
  if (restoringWorkspaceState) return;
  window.localStorage.setItem(LOCATION_STORAGE_KEY, JSON.stringify(currentLocation.value));
  window.localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify(expandedFolderKeys.value));
  window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, assetViewMode.value);
  window.localStorage.setItem(PAGE_STORAGE_KEY, JSON.stringify(pagesByLocation.value));
  window.localStorage.setItem(ACTIVE_VIEW_STORAGE_KEY, normalizePrimaryView(view.value));
  window.localStorage.setItem(FAVORITE_CONTEXT_STORAGE_KEY, favoriteContext.value ? "true" : "false");
}

function rememberCurrentPage() {
  pagesByLocation.value = {
    ...pagesByLocation.value,
    [workspaceLocationKey(currentLocation.value)]: currentPage.value,
  };
  persistWorkspaceState();
}

async function loadFolderChildren(sourceId, parent = "", force = false) {
  if (!sourceId) return [];
  const key = folderKey(sourceId, parent);
  if (parent) return [];
  if (!force && folderChildrenByKey[key]) return folderChildrenByKey[key];
  if (!folderLoadingKeys.value.includes(key)) folderLoadingKeys.value = [...folderLoadingKeys.value, key];
  delete folderErrors[key];
  try {
    const query = buildAssetQuery({ source: sourceId, parent, type: standalone.value ? "" : "video" });
    const data = await api.get(`/api/folders?${query}`);
    folderChildrenByKey[key] = (data.items || []).map((item) => ({
      ...item,
      has_children: false,
    }));
    return folderChildrenByKey[key];
  } catch (reason) {
    folderErrors[key] = reason?.message || "文件夹读取失败";
    throw reason;
  } finally {
    folderLoadingKeys.value = folderLoadingKeys.value.filter((item) => item !== key);
  }
}

async function hydratePhysicalLocation(location) {
  if (!["source", "folder"].includes(location.kind)) return;
  const sourceId = location.sourceId;
  const folder = location.folder || "";
  const rootKey = folderKey(sourceId, "");
  expandedFolderKeys.value = [...new Set([...expandedFolderKeys.value, rootKey])];
  await loadFolderChildren(sourceId, "").catch(() => []);
  persistWorkspaceState();
}

async function toggleFolderTree({ sourceId, folder = "", retry = false }) {
  if (folder) return;
  const key = folderKey(sourceId, folder);
  const expanded = expandedFolderKeys.value.includes(key);
  if (expanded && !retry) {
    expandedFolderKeys.value = expandedFolderKeys.value.filter((item) => item !== key);
    persistWorkspaceState();
    return;
  }
  if (!expanded) expandedFolderKeys.value = [...expandedFolderKeys.value, key];
  persistWorkspaceState();
  await loadFolderChildren(sourceId, folder, retry).catch(showError);
}

async function loadAssets({ page = currentPage.value } = {}) {
  const scanId = completedScanId.value;
  const requestedPage = Math.max(1, Math.floor(Number(page) || 1));
  const queryFilters = { ...filters };
  if (queryFilters.date_from) queryFilters.date_from = new Date(`${queryFilters.date_from}T00:00:00`).getTime() / 1000;
  if (queryFilters.date_to) queryFilters.date_to = new Date(`${queryFilters.date_to}T23:59:59`).getTime() / 1000 + 1;
  queryFilters.offset = (requestedPage - 1) * ASSET_PAGE_SIZE;
  queryFilters.limit = ASSET_PAGE_SIZE;
  const query = buildAssetQuery(queryFilters);
  let data = await api.get(`/api/assets${query ? `?${query}` : ""}`);
  const total = Number(data.total ?? data.count ?? data.items.length);
  const resolved = paginationModel(total, requestedPage, ASSET_PAGE_SIZE);
  if (resolved.page !== requestedPage) {
    queryFilters.offset = resolved.offset;
    const fallbackQuery = buildAssetQuery(queryFilters);
    data = await api.get(`/api/assets${fallbackQuery ? `?${fallbackQuery}` : ""}`);
  }
  currentPage.value = resolved.page;
  assets.value = data.items;
  totalAssets.value = total;
  hiddenAssets.value = Number(data.hidden_count || 0);
  listedScanId = scanId;
  rememberCurrentPage();
}

function selectCaptureIntakePreset() {
  if (captureFilters.intake_time === "custom") return;
  const range = captureDateRange(captureFilters);
  const dateValue = (seconds) => {
    if (seconds == null) return "";
    const date = new Date(seconds * 1000);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  };
  captureFilters.intake_start = dateValue(range.created_from);
  captureFilters.intake_end = dateValue(range.created_before == null ? null : range.created_before - 1);
}

async function loadCaptures({ page = capturePage.value } = {}) {
  const requestedPage = Math.max(1, Math.floor(Number(page) || 1));
  const query = buildAssetQuery({
    ...captureRequestFilters(captureFilters, { favoriteLinks: favoriteContext.value }),
    limit: CAPTURE_PAGE_SIZE,
    offset: (requestedPage - 1) * CAPTURE_PAGE_SIZE,
  });
  let data = await api.get(`/api/captures?${query}`);
  const total = Number(data.total || 0);
  const resolved = paginationModel(total, requestedPage, CAPTURE_PAGE_SIZE);
  if (resolved.page !== requestedPage) {
    const fallbackQuery = buildAssetQuery({
      ...captureRequestFilters(captureFilters, { favoriteLinks: favoriteContext.value }),
      limit: CAPTURE_PAGE_SIZE,
      offset: resolved.offset,
    });
    data = await api.get(`/api/captures?${fallbackQuery}`);
  }
  captures.value = data.items || [];
  captureTotal.value = total;
  captureCount.value = Math.max(captureCount.value, total);
  captureStats.value = data.stats || { platforms: {}, statuses: {}, kinds: {} };
  capturePage.value = resolved.page;
}

async function goToCapturePage(page) {
  if (captureLoading.value) return;
  captureLoading.value = true;
  try {
    await loadCaptures({ page });
    resetVisiblePage();
  } catch (reason) {
    showError(reason);
  } finally {
    captureLoading.value = false;
  }
}

async function goToPage(page) {
  const target = paginationModel(totalAssets.value, page, ASSET_PAGE_SIZE).page;
  if (target === currentPage.value || pageLoading.value) return;
  pageLoading.value = true;
  try {
    await loadAssets({ page: target });
    await nextTick();
    document.querySelector(".workspace-organize-toolbar")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (reason) {
    showError(reason);
  } finally {
    pageLoading.value = false;
  }
}

async function refresh() {
  try {
    await bootstrap();
    if (view.value === "captures") {
      await loadCaptures();
    } else if (view.value === "assets") {
      const normalized = normalizeWorkspaceLocation(currentLocation.value, workspaceContext());
      if (JSON.stringify(normalized) !== JSON.stringify(currentLocation.value)) {
        await selectWorkspaceLocation(normalized);
      } else {
        await loadAssets();
        if (isPhysicalLocation.value) await loadFolderChildren(filters.source, filters.folder, true);
      }
    }
  } catch (reason) {
    showError(reason);
  } finally {
    loading.value = false;
  }
}

function openHome() {
  favoriteContext.value = false;
  view.value = "home";
  persistWorkspaceState();
  resetVisiblePage();
}

async function openCaptures() {
  favoriteContext.value = false;
  view.value = "captures";
  persistWorkspaceState();
  treeDrawerOpen.value = false;
  capturePage.value = 1;
  await loadCaptures().catch(showError);
  resetVisiblePage();
}

async function selectWorkspaceLocation(requestedLocation, { remember = true } = {}) {
  const location = normalizeWorkspaceLocation(requestedLocation, workspaceContext());
  favoriteContext.value = false;
  currentLocation.value = location;
  const storedPage = Number(pagesByLocation.value[workspaceLocationKey(location)] || 1);
  currentPage.value = Number.isFinite(storedPage) && storedPage > 0 ? Math.floor(storedPage) : 1;
  view.value = "assets";
  ignoreFilterWatch = true;
  Object.assign(filters, {
    category: "",
    collection: "",
    source: "",
    folder: "",
    folder_scope: "recursive",
    status: "",
    lifecycle_stage: "",
    favorite: false,
    type: "video",
    availability: "available",
  }, workspaceFilters(location, standalone.value ? "" : "video"));
  await nextTick();
  ignoreFilterWatch = false;
  selectedIds.value = [];
  packMenuOpen.value = false;
  treeDrawerOpen.value = false;
  if (remember) persistWorkspaceState();
  if (isPhysicalLocation.value) await hydratePhysicalLocation(location);
  await loadAssets().catch(showError);
  resetVisiblePage();
}

async function openAssets(category = "") {
  await selectWorkspaceLocation(category ? { kind: "category", category } : { kind: "all" });
}
async function enterFolder(folder) {
  await selectWorkspaceLocation({ kind: "folder", sourceId: folder.source_id, folder: folder.path });
}
async function goToParentFolder() {
  const parts = filters.folder.split("/").filter(Boolean);
  parts.pop();
  await selectWorkspaceLocation(parts.length
    ? { kind: "folder", sourceId: filters.source, folder: parts.join("/") }
    : { kind: "source", sourceId: filters.source, folder: "" });
}
async function openFavorites() {
  await selectFavoriteTab(favoriteTab.value);
}

async function selectFavoriteTab(requestedTab) {
  const tab = normalizeFavoriteTab(requestedTab);
  favoriteTab.value = tab;
  window.localStorage.setItem(FAVORITE_TAB_STORAGE_KEY, tab);
  if (tab === "captures") {
    currentLocation.value = { kind: "favorites" };
    favoriteContext.value = true;
    view.value = "captures";
    capturePage.value = 1;
    treeDrawerOpen.value = false;
    persistWorkspaceState();
    await loadCaptures({ page: 1 }).catch(showError);
    resetVisiblePage();
    return;
  }
  await selectWorkspaceLocation({ kind: "favorites" });
}
async function openCollection(collection) {
  await selectWorkspaceLocation({ kind: "collection", collectionId: collection.id });
}
function openSettings() {
  favoriteContext.value = false;
  view.value = "settings";
  persistWorkspaceState();
  resetVisiblePage();
}

function capturePlatformLabel(platform) {
  return {
    douyin: "抖音",
    xiaohongshu: "小红书",
    bilibili: "B 站",
    x: "X",
    youtube: "YouTube",
    web: "网页",
  }[platform] || platform || "网页";
}

watch(
  () => [filters.q, filters.type, filters.orientation, filters.status, filters.lifecycle_stage, filters.date_from, filters.date_to, filters.dedupe],
  () => {
    if (view.value !== "assets" || ignoreFilterWatch) return;
    currentPage.value = 1;
    rememberCurrentPage();
    window.clearTimeout(filterLoadTimer);
    filterLoadTimer = window.setTimeout(() => loadAssets().catch(showError), 180);
  },
);

watch(
  () => [captureFilters.q, captureFilters.content_kind, captureFilters.category, captureFilters.platform, captureFilters.status, captureFilters.favorite, captureFilters.intake_time, captureFilters.intake_start, captureFilters.intake_end],
  () => {
    if (view.value !== "captures") return;
    capturePage.value = 1;
    window.clearTimeout(captureFilterTimer);
    captureFilterTimer = window.setTimeout(() => loadCaptures().catch(showError), 180);
  },
);

async function openAsset(asset) {
  selected.value = asset;
  duplicateCopies.value = [];
  editor.display_name = asset.display_name || filename(asset.relative_path);
  editor.note = asset.note || "";
  editor.tags = (asset.tags || []).join("，");
  editor.categories = confirmedCategories(asset).map((item) => item.name);
  editor.collections = asset.collection_ids || [];
  editor.lifecycle_stage = asset.lifecycle_stage || "needs_review";
  if (standalone.value) return;
  if (asset.exact_duplicate_count) {
    const data = await api.get(`/api/assets/${asset.id}/duplicates`).catch((reason) => {
      showError(reason);
      return { items: [] };
    });
    duplicateCopies.value = data.items || [];
  }
}
async function trashDuplicateCopies() {
  if (!selected.value || !duplicateCleanup.value.copyCount) return;
  const summary = duplicateCleanup.value;
  const confirmed = window.confirm(
    `确认保留：${summary.keeperLabel}\n\n` +
    `把另外 ${summary.copyCount} 份完整内容相同的原文件移入 Mac 废纸篓？\n` +
    `预计释放 ${formatBytes(summary.reclaimableBytes)}，清空废纸篓前可恢复。`,
  );
  if (!confirmed) return;
  busy.value = true;
  try {
    const keeperId = selected.value.id;
    const result = await api.post(`/api/assets/${keeperId}/trash-duplicates`);
    if (!result.moved_count) {
      throw new Error(result.failed?.[0]?.error || "清理前重新校验未通过，没有移动任何原文件");
    }
    showNotice(
      `已把 ${result.moved_count} 份原文件移入废纸篓，释放 ${formatBytes(result.reclaimed_bytes)}` +
      (result.failed_count ? `；${result.failed_count} 份未移动` : ""),
    );
    await bootstrap();
    await loadAssets();
    const updated = await api.get(`/api/assets/${keeperId}`);
    await openAsset(updated);
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}
function closeAsset() {
  selected.value = null;
  duplicateCopies.value = [];
}

async function toggleFavorite(asset) {
  try {
    const updated = await api.patch(`/api/assets/${asset.id}/favorite`, { favorite: !asset.favorite });
    Object.assign(asset, updated);
    if (selected.value?.id === asset.id) Object.assign(selected.value, updated);
  } catch (reason) {
    showError(reason);
  }
}
async function saveEditor() {
  if (!selected.value) return;
  busy.value = true;
  try {
    const previous = confirmedCategories(selected.value).map((item) => item.name);
    const tags = editor.tags.split(/[，,]/).map((item) => item.trim()).filter(Boolean);
    const updated = await api.patch(`/api/assets/${selected.value.id}/metadata`, {
      display_name: editor.display_name,
      note: editor.note,
      add_tags: tags,
      remove_tags: (selected.value.tags || []).filter((tag) => !tags.includes(tag)),
      manual_categories: editor.categories.filter((name) => !previous.includes(name)),
      remove_categories: previous.filter((name) => !editor.categories.includes(name)),
    });
    const staged = editor.lifecycle_stage === selected.value.lifecycle_stage
      ? updated
      : await api.patch(`/api/assets/${selected.value.id}/stage`, { stage: editor.lifecycle_stage });
    await api.patch(`/api/assets/${selected.value.id}/collections`, { collection_ids: editor.collections });
    Object.assign(selected.value, staged, { collection_ids: [...editor.collections] });
    const card = assets.value.find((item) => item.id === staged.id);
    if (card) Object.assign(card, staged);
    await bootstrap();
    showNotice("修改已保存，只更新了素材库索引");
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}
async function confirmTagCandidate(asset, tag) {
  try {
    const updated = await api.patch(`/api/assets/${asset.id}/metadata`, { confirm_tag_candidates: [tag] });
    Object.assign(asset, updated);
    if (selected.value?.id === asset.id) {
      Object.assign(selected.value, updated);
      editor.tags = (updated.tags || []).join("，");
    }
    showNotice(`已确认标签“${tag}”`);
  } catch (reason) {
    showError(reason);
  }
}
async function reveal(asset) {
  try {
    await api.post(`/api/assets/${asset.id}/reveal`);
  } catch (reason) {
    showError(reason);
  }
}
async function revealCurrentFolder() {
  if (!isPhysicalLocation.value) return;
  try {
    await api.post("/api/folders/reveal", {
      source_id: filters.source,
      folder: filters.folder,
    });
  } catch (reason) {
    showError(reason);
  }
}
function setAssetViewMode(mode) {
  assetViewMode.value = mode === "list" ? "list" : "grid";
  persistWorkspaceState();
}
async function relocateAsset(asset) {
  busy.value = true;
  try {
    const updated = await api.post(`/api/assets/${asset.id}/relocate`);
    Object.assign(asset, updated);
    if (selected.value?.id === asset.id) Object.assign(selected.value, updated);
    showNotice("已重新关联新位置，标签和备注都保留了");
  } catch (reason) {
    if (!String(reason?.message).includes("User canceled")) showError(reason);
  } finally {
    busy.value = false;
  }
}
async function removeAssetIndex(asset) {
  if (!window.confirm("只从素材库移除这条索引？原文件不会删除。")) return;
  try {
    await api.delete(`/api/assets/${asset.id}`);
    assets.value = assets.value.filter((item) => item.id !== asset.id);
    totalAssets.value = Math.max(0, totalAssets.value - 1);
    closeAsset();
    showNotice("索引已移除，原文件没有改动");
  } catch (reason) {
    showError(reason);
  }
}
function toggleSelect(assetId) {
  selectedIds.value = selectedIds.value.includes(assetId)
    ? selectedIds.value.filter((id) => id !== assetId)
    : [...selectedIds.value, assetId];
}
async function batchTag() {
  const tag = window.prompt("给选中的素材加什么标签？");
  if (!tag) return;
  try {
    await api.post("/api/assets/batch/tags", { asset_ids: selectedIds.value, tags: [tag] });
    selectedIds.value = [];
    await loadAssets();
    showNotice("批量标签已添加");
  } catch (reason) {
    showError(reason);
  }
}
async function batchSetLifecycleStage() {
  if (!selectedIds.value.length || !batchLifecycleStage.value) return;
  try {
    const result = await api.patch("/api/assets/batch/stage", {
      asset_ids: selectedIds.value,
      stage: batchLifecycleStage.value,
    });
    const label = assetLifecycleStageLabel(result.stage);
    selectedIds.value = [];
    batchLifecycleStage.value = "";
    await Promise.all([bootstrap(), loadAssets()]);
    showNotice(`已将 ${result.updated} 条素材标为“${label}”`);
  } catch (reason) {
    showError(reason);
  }
}
async function packSelected() {
  if (!selectedIds.value.length) return;
  const name = window.prompt("这个素材包叫什么？");
  if (!name) return;
  try {
    const collection = await api.post("/api/collections", {
      name,
      asset_ids: selectedIds.value,
    });
    selectedIds.value = [];
    await bootstrap();
    showNotice(`已把 ${collection.asset_count} 条素材放进“${collection.name}”`);
  } catch (reason) {
    showError(reason);
  }
}
async function packCurrentResults({ includeNested = false } = {}) {
  if (!totalAssets.value && !(includeNested && isPhysicalLocation.value)) return;
  const name = window.prompt("当前这些素材要打成什么包？");
  if (!name) return;
  try {
    const queryFilters = { ...filters };
    if (isPhysicalLocation.value) {
      queryFilters.folder_scope = includeNested ? "recursive" : "direct";
    }
    if (queryFilters.date_from) queryFilters.date_from = new Date(`${queryFilters.date_from}T00:00:00`).getTime() / 1000;
    if (queryFilters.date_to) queryFilters.date_to = new Date(`${queryFilters.date_to}T23:59:59`).getTime() / 1000 + 1;
    const collection = await api.post("/api/collections/from-filter", {
      name,
      filters: queryFilters,
    });
    await bootstrap();
    packMenuOpen.value = false;
    showNotice(`已把当前 ${collection.asset_count} 条素材打成“${collection.name}”`);
  } catch (reason) {
    showError(reason);
  }
}
async function confirmSelectedCandidates() {
  if (!filters.category || filters.status !== "candidate" || !selectedIds.value.length) return;
  try {
    await Promise.all(
      selectedIds.value.map((assetId) =>
        api.patch(`/api/assets/${assetId}/metadata`, { confirm_categories: [filters.category] }),
      ),
    );
    const count = selectedIds.value.length;
    selectedIds.value = [];
    await Promise.all([bootstrap(), loadAssets()]);
    showNotice(`已确认 ${count} 条“${filters.category}”候选`);
  } catch (reason) {
    showError(reason);
  }
}
async function addSource() {
  busy.value = true;
  try {
    const picked = await api.post("/api/sources/pick");
    if (!picked.path) return;
    const source = await api.post("/api/sources", { path: picked.path });
    await api.post("/api/scans", { source_ids: [source.id] });
    await bootstrap();
    showNotice("来源已加入，正在读取素材");
  } catch (reason) {
    if (!String(reason?.message).includes("User canceled")) showError(reason);
  } finally {
    busy.value = false;
  }
}
async function scanAll() {
  try {
    await api.post("/api/scans");
    await bootstrap();
    showNotice("已开始刷新素材");
  } catch (reason) {
    showError(reason);
  }
}

async function confirmMissingReview(scan) {
  if (!scan || scan.commit_status !== "review_required") return;
  const preview = scan.missing_candidates
    .slice(0, 8)
    .map((item) => `· ${item.relative_path}`)
    .join("\n");
  const confirmed = window.confirm(
    `${scan.sourceName}拟标记 ${scan.proposedMissing} 条失效索引：\n${preview}`
      + `${scan.missing_candidates.length > 8 ? `\n…共 ${scan.missing_candidates.length} 条` : ""}`
      + "\n\n确认时会重新检查扫描世代、候选集和原路径。只更新索引，不删除或移动原文件。是否继续？",
  );
  if (!confirmed) return;
  busy.value = true;
  try {
    const result = await api.post(`/api/scans/${scan.id}/confirm-missing`);
    await bootstrap();
    if (view.value === "assets") await loadAssets();
    showNotice(`已确认 ${result.committed || 0} 条失效索引，原文件没有改动`);
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function previewMissingRecovery() {
  busy.value = true;
  try {
    recoveryPreview.value = await api.post("/api/assets/recover-missing", { dry_run: true });
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function commitMissingRecovery() {
  const preview = recoveryPreview.value;
  if (!preview || !preview.dry_run || !preview.would_restore) return;
  const confirmed = window.confirm(
    `预计恢复 ${preview.would_restore} 条、拒绝 ${preview.rejected?.length || 0} 条。\n\n继续后只恢复与原索引完全匹配的记录，不改原文件。是否确认？`,
  );
  if (!confirmed) return;
  busy.value = true;
  try {
    const result = await api.post("/api/assets/recover-missing", { dry_run: false });
    recoveryPreview.value = result;
    await bootstrap();
    if (view.value === "assets") await loadAssets();
    showNotice(`已恢复 ${result.restored || 0} 条误失效索引，原文件没有改动`);
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}

async function openPrivacySettings() {
  busy.value = true;
  try {
    const result = await api.post("/api/system/open-privacy-settings");
    privacyProgramPath.value = result.program_path || "";
    showNotice("已定位实际后台程序并打开系统设置；尚未授权，返回后请手动重新扫描");
  } catch (reason) {
    showError(reason);
  } finally {
    busy.value = false;
  }
}
async function toggleScanPause() {
  try {
    await api.post(scanQueue.value.status === "paused" ? "/api/scans/resume" : "/api/scans/pause");
    await bootstrap();
  } catch (reason) {
    showError(reason);
  }
}
async function startDuplicateVerification() {
  try {
    await api.post("/api/duplicates/verify");
    await bootstrap();
    showNotice("正在完整读取疑似重复文件，只校验，不删除");
  } catch (reason) {
    showError(reason);
  }
}
async function toggleDuplicatePause() {
  try {
    await api.post(duplicates.value.status === "paused" ? "/api/duplicates/resume" : "/api/duplicates/pause");
    await bootstrap();
  } catch (reason) {
    showError(reason);
  }
}
async function removeSource(source) {
  if (!window.confirm(`只从素材库移除“${source.name}”的索引？原文件不会删除。`)) return;
  try {
    await api.delete(`/api/sources/${source.id}`);
    await bootstrap();
    showNotice("索引已移除，原文件没有改动");
  } catch (reason) {
    showError(reason);
  }
}
async function createCollection() {
  const name = window.prompt("新集合叫什么？");
  if (!name) return;
  try {
    await api.post("/api/collections", { name });
    await bootstrap();
  } catch (reason) {
    showError(reason);
  }
}
async function stopStandaloneLibrary() {
  try {
    await api.post("/api/service/stop");
    showNotice("素材库已退出，可以关闭这个页面。");
  } catch (reason) {
    showError(reason);
  }
}

async function restartService() {
  if (!window.confirm("重启素材库后台服务？素材和索引不会受影响。")) return;
  await api.post("/api/service/stop").catch(showError);
  showNotice("后台服务正在自动重启，页面稍后刷新");
  window.setTimeout(() => window.location.reload(), 1600);
}

function thumbUrl(asset) {
  return `/api/assets/${asset.id}/thumbnail`;
}
function cardMeta(asset) {
  if (asset.media_type === "video" || asset.media_type === "audio") return formatDuration(asset.duration);
  if (asset.width && asset.height) return `${asset.width} × ${asset.height}`;
  return formatBytes(asset.size);
}
function typeName(type) {
  return { video: "视频", image: "图片", audio: "音频" }[type] || type;
}
function assetName(asset) {
  return asset.display_name || filename(asset.relative_path);
}
function assetFolder(asset) {
  const parts = String(asset.relative_path || "").split("/").filter(Boolean);
  parts.pop();
  return parts.join(" / ");
}

onMounted(async () => {
  restoringWorkspaceState = true;
  try {
    await bootstrap();
    const preferredView = normalizePrimaryView(
      window.localStorage.getItem(ACTIVE_VIEW_STORAGE_KEY),
    );
    const storedPrimaryView = standalone.value && !["assets", "captures", "settings"].includes(preferredView)
      ? "assets" : preferredView;
    favoriteTab.value = normalizeFavoriteTab(window.localStorage.getItem(FAVORITE_TAB_STORAGE_KEY));
    const storedFavoriteContext = window.localStorage.getItem(FAVORITE_CONTEXT_STORAGE_KEY) === "true";
    const storedExpanded = readStoredJson(EXPANDED_STORAGE_KEY, []);
    expandedFolderKeys.value = Array.isArray(storedExpanded)
      ? storedExpanded.filter((item) => typeof item === "string" && !item.startsWith("/"))
      : [];
    const storedPages = readStoredJson(PAGE_STORAGE_KEY, {});
    pagesByLocation.value = storedPages && typeof storedPages === "object" && !Array.isArray(storedPages)
      ? Object.fromEntries(Object.entries(storedPages).filter(([key, value]) => (
        /^(all|favorites|candidates|missing|source:|folder:|category:|collection:|stage:)/.test(key) &&
        Number.isFinite(Number(value)) && Number(value) > 0
      )))
      : {};
    assetViewMode.value = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY) === "list" ? "list" : "grid";
    const storedLocation = readStoredJson(LOCATION_STORAGE_KEY, { kind: "all" });
    const location = normalizeWorkspaceLocation(storedLocation, workspaceContext());
    await selectWorkspaceLocation(location, { remember: false });
    view.value = storedPrimaryView;
    favoriteContext.value = storedPrimaryView === "captures"
      && location.kind === "favorites"
      && favoriteTab.value === "captures"
      && storedFavoriteContext;
    if (storedPrimaryView === "captures") await loadCaptures().catch(showError);
    restoringWorkspaceState = false;
    persistWorkspaceState();
  } catch (reason) {
    restoringWorkspaceState = false;
    showError(reason);
  } finally {
    restoringWorkspaceState = false;
    loading.value = false;
  }
  poller = window.setInterval(async () => {
    if (document.hidden) return;
    await bootstrap().catch(() => {});
    if (view.value === "captures") {
      await loadCaptures().catch(() => {});
    } else if (
      view.value === "assets" &&
      (
        scans.value.some((item) => item.status === "running") ||
        duplicates.value.status === "running" ||
        (standalone.value && completedScanId.value !== listedScanId)
      )
    ) {
      await loadAssets().catch(() => {});
      if (isPhysicalLocation.value) {
        await loadFolderChildren(filters.source, filters.folder, true).catch(() => {});
      }
    }
  }, 2500);
});
onBeforeUnmount(() => {
  closeCaptureEditor();
  window.clearInterval(poller);
  window.clearTimeout(filterLoadTimer);
  window.clearTimeout(captureFilterTimer);
});
</script>

<template>
  <div class="shell" :style="comfortableTypographyVars()">
    <main class="main">
      <p v-if="!mediaToolsReady" class="media-tools-notice" role="status">
        可继续收集作品链接。要扫描本地素材或保存原件，请按安装说明安装 FFmpeg 和 FFprobe，然后重新打开素材库。
      </p>
      <MaterialWorkspace
        :view="view"
        :active-navigation="activeNavigation"
        :sources="sources"
        :collections="collections"
        :location="currentLocation" :standalone="standalone"
        :capture-count="captureCount"
        :missing-count="missingCount"
        :expanded-keys="expandedFolderKeys"
        :children-by-key="folderChildrenByKey"
        :loading-keys="folderLoadingKeys"
        :error-by-key="folderErrors"
        :drawer-open="treeDrawerOpen"
        @select="selectWorkspaceLocation"
        @toggle="toggleFolderTree"
        @create-collection="createCollection"
        @close-drawer="treeDrawerOpen = false"
        @open-drawer="treeDrawerOpen = true"
        @open-home="openHome"
        @open-assets="openAssets()"
        @open-favorites="openFavorites"
        @open-captures="openCaptures"
        @open-settings="openSettings"
      >
      <header v-if="view !== 'assets'" class="topbar">
        <div>
          <p class="eyebrow">MUYI MATERIAL LIBRARY</p>
          <h1>{{ title }}</h1>
          <p>{{ subtitle }}</p>
        </div>
        <div class="top-actions">
          <template v-if="view === 'captures'">
            <button class="ghost-button" :disabled="captureLoading" @click="goToCapturePage(capturePage)">↻ 刷新链接</button>
          </template>
          <template v-else>
            <button v-if="scanQueue.status !== 'idle'" class="scan-chip" @click="toggleScanPause"><span class="pulse"></span>{{ scanQueue.status === 'paused' ? '已暂停，点此继续' : `正在读取 ${runningScan?.processed || 0}/${runningScan?.found || 0}，点此暂停` }}</button>
            <button class="ghost-button" @click="scanAll">↻ 刷新素材</button>
            <button class="primary-button" :disabled="busy" @click="addSource">＋ 添加来源</button>
          </template>
        </div>
      </header>

      <div v-if="error" class="toast error-toast">{{ error }}</div>
      <div v-if="notice" class="toast success-toast">{{ notice }}</div>

      <section v-if="loading" class="loading-state"><span></span><p>正在打开你的素材库…</p></section>

      <template v-else-if="view === 'home'">
        <section class="organize-panel">
          <div><span>▤</span><p><strong>本地视频文件夹</strong><small>现在只读取“视频发布”和“新人视频发布”，原文件保持原位。</small></p><b>{{ sources.length }} 个来源</b></div>
          <div><span>≡</span><p><strong>完整去重</strong><small>先读取完整文件确认相同；你选定保留件后，其他原文件才能进入废纸篓。</small></p><button v-if="duplicates.status === 'idle'" @click="startDuplicateVerification">{{ duplicates.pending_assets ? `校验 ${duplicates.pending_assets} 条` : '重新检查重复' }}</button><button v-else @click="toggleDuplicatePause">{{ duplicates.status === 'paused' ? '继续校验' : `${duplicates.processed || 0}/${duplicates.total || 0}，暂停` }}</button></div>
        </section>

        <section class="source-glance">
          <div class="section-title"><div><h2>本地视频来源</h2><p>只索引你选定的两个发布文件夹，不扫描整台 Mac</p></div><button @click="openSettings">管理来源</button></div>
          <div class="source-pills">
            <div v-for="source in sources" :key="source.id"><i :class="source.status"></i><span>{{ source.name }}</span><small>{{ source.status === 'missing' ? '文件夹不在了' : '已连接' }}</small></div>
          </div>
        </section>
      </template>

      <template v-else-if="view === 'captures'">
        <nav v-if="favoriteContext" class="favorite-tabs" aria-label="收藏类型">
          <button :class="{ active: favoriteTab === 'assets' }" @click="selectFavoriteTab('assets')">本机素材</button>
          <button :class="{ active: favoriteTab === 'captures' }" @click="selectFavoriteTab('captures')">链接素材</button>
        </nav>
        <section class="capture-guide">
          <span>⌥</span>
          <div><strong>按住 Option，再点视频或图片，直接入库</strong><p>不用先点扩展图标。旧的 ⌘⇧8 和扩展图标仍可进入紫色点选模式；保存素材链接、封面和作品信息。</p></div>
          <kbd>⌥ + 点素材</kbd>
        </section>

        <section class="capture-filter-bar">
          <label class="search"><span>⌕</span><input v-model.trim="captureFilters.q" placeholder="搜标题、作者、标签、备注、链接或作品 ID" /></label>
          <select v-model="captureFilters.content_kind">
            <option value="">全部类型（{{ (captureStats.kinds?.video || 0) + (captureStats.kinds?.image || 0) }}）</option>
            <option value="video">视频（{{ captureStats.kinds?.video || 0 }}）</option>
            <option value="image">图片（{{ captureStats.kinds?.image || 0 }}）</option>
          </select>
          <select v-model="captureFilters.category">
            <option value="">全部用途</option>
            <option v-for="category in captureCategories" :key="category.id" :value="category.name">{{ category.name }}（{{ category.count || 0 }}）</option>
          </select>
          <select v-model="captureFilters.platform">
            <option value="">全部平台</option>
            <option v-for="([platform, count]) in capturePlatforms" :key="platform" :value="platform">{{ capturePlatformLabel(platform) }}（{{ count }}）</option>
          </select>
          <select v-model="captureFilters.status">
            <option value="">全部状态</option>
            <option value="saved">已收集</option>
            <option value="downloaded">已保存到本地</option>
            <option value="download_failed">本地保存失败</option>
            <option value="capture_pending">待重新采集</option>
          </select>
          <span v-if="favoriteContext" class="capture-favorite-fixed">只显示收藏</span>
          <label v-else class="capture-favorite-filter"><input v-model="captureFilters.favorite" type="checkbox" /> 只看收藏</label>
          <div class="capture-secondary-filters">
            <button class="capture-purpose-manage-button" type="button" @click="openCapturePurposeManager">管理链接用途</button>
            <div class="capture-time-controls">
            <label class="capture-intake-filter capture-intake-select"><span>入库时间</span>
              <select v-model="captureFilters.intake_time" aria-label="入库时间" @change="selectCaptureIntakePreset">
                <option value="">全部时间</option>
                <option value="today">今天</option>
                <option value="yesterday">昨天</option>
                <option value="7d">最近 7 天</option>
                <option value="30d">最近 30 天</option>
                <option v-if="captureFilters.intake_time === 'custom'" value="custom">自定义日期</option>
              </select>
            </label>
              <label class="capture-intake-filter">从 <input v-model="captureFilters.intake_start" @change="captureFilters.intake_time = 'custom'" type="date" aria-label="入库开始日期" :max="captureFilters.intake_end || undefined" /></label>
              <label class="capture-intake-filter">至 <input v-model="captureFilters.intake_end" @change="captureFilters.intake_time = 'custom'" type="date" aria-label="入库结束日期" :min="captureFilters.intake_start || undefined" /></label>
            </div>
          </div>
        </section>

        <section v-if="captures.length" class="capture-grid" :class="{ loading: captureLoading }">
          <CaptureCard
            v-for="capture in captures"
            :key="capture.id"
            :capture="capture"
            :busy="busy"
            :saving="captureSavingId === capture.id"
            :platform-label="capturePlatformLabel"
            :preview-state="capture.media_refresh_status"
            @open="openCaptureEditor"
            @toggle-favorite="toggleCaptureFavorite"
            @delete="deleteCapture"
            @repair-thumbnail="repairCaptureThumbnailAutomatically"
            @save-local="saveCaptureLocal"
          />
        </section>

        <nav v-if="captureTotal" class="asset-pagination capture-pagination" aria-label="链接分页">
          <span class="page-summary">{{ captureRangeLabel }}</span>
          <button :disabled="capturePagination.page === 1 || captureLoading" @click="goToCapturePage(capturePagination.page - 1)">‹</button>
          <template v-for="item in capturePagination.items" :key="item">
            <span v-if="typeof item === 'string'" class="page-ellipsis">…</span>
            <button v-else :class="{ active: item === capturePagination.page }" :disabled="captureLoading" @click="goToCapturePage(item)">{{ item }}</button>
          </template>
          <button :disabled="capturePagination.page === capturePagination.pageCount || captureLoading" @click="goToCapturePage(capturePagination.page + 1)">›</button>
        </nav>

        <section v-if="!captures.length" class="empty-state capture-empty"><span>⌥</span><h2>还没有收集的网页素材</h2><p>打开网页，按住 Alt 或 Option 再点视频或图片。</p></section>
      </template>

      <template v-else-if="view === 'assets'">
          <header class="workspace-header">
            <div class="workspace-heading">
              <button class="folder-drawer-button" @click="treeDrawerOpen = true">☰ 文件夹</button>
              <nav class="workspace-breadcrumb" aria-label="当前位置">
                <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb.label}:${index}`">
                  <span v-if="index">/</span>
                  <button :disabled="index === breadcrumbs.length - 1" @click="selectWorkspaceLocation(crumb.location)">{{ crumb.label }}</button>
                </template>
              </nav>
              <h1>{{ title }}</h1>
              <p>{{ subtitle }}</p>
            </div>
            <div class="workspace-actions">
              <button v-if="scanQueue.status !== 'idle'" class="scan-chip" @click="toggleScanPause"><span class="pulse"></span>{{ scanQueue.status === 'paused' ? '扫描已暂停' : '正在扫描' }}</button>
              <div class="view-switch" aria-label="素材显示方式"><button :class="{ active: assetViewMode === 'grid' }" title="瀑布流显示" @click="setAssetViewMode('grid')">▦</button><button :class="{ active: assetViewMode === 'list' }" title="列表显示" @click="setAssetViewMode('list')">☷</button></div>
              <button v-if="isPhysicalLocation" class="ghost-button" @click="revealCurrentFolder">{{ standalone ? "打开文件夹" : "在 Finder 中显示" }}</button>
              <div v-if="currentLocation.kind !== 'missing'" class="pack-menu">
                <button class="primary-button" :disabled="!totalAssets && !childFolders.length" @click="isPhysicalLocation ? (packMenuOpen = !packMenuOpen) : packCurrentResults()">▤ 打成素材包 <span v-if="isPhysicalLocation">⌄</span></button>
                <div v-if="packMenuOpen && isPhysicalLocation" class="pack-menu-popover">
                  <button :disabled="!totalAssets" @click="packCurrentResults({ includeNested: false })"><strong>仅当前层</strong><small>只收右侧现在看到的素材</small></button>
                  <button @click="packCurrentResults({ includeNested: true })"><strong>包含全部子文件夹</strong><small>把整个目录树收入素材包</small></button>
                </div>
              </div>
            </div>
          </header>

          <nav v-if="currentLocation.kind === 'favorites'" class="favorite-tabs workspace-favorite-tabs" aria-label="收藏类型">
            <button :class="{ active: favoriteTab === 'assets' }" @click="selectFavoriteTab('assets')">本机素材</button>
            <button :class="{ active: favoriteTab === 'captures' }" @click="selectFavoriteTab('captures')">链接素材</button>
          </nav>

          <div class="workspace-body">
            <section class="workspace-filter-bar">
              <label class="search"><span>⌕</span><input v-model.trim="filters.q" :placeholder="`在“${title}”中搜索名称、标签或备注`" /></label>
              <select v-model="filters.orientation"><option value="">全部方向</option><option value="vertical">竖版</option><option value="horizontal">横版</option><option value="square">方形</option></select>
              <select v-model="filters.lifecycle_stage" aria-label="素材状态"><option value="">全部素材状态</option><option v-for="stage in lifecycleStages" :key="stage.id" :value="stage.id">{{ stage.label }}（{{ stage.count }}）</option></select>
              <label class="date-filter"><span>开始日期</span><input v-model="filters.date_from" type="date" /></label>
              <label class="date-filter"><span>结束日期</span><input v-model="filters.date_to" type="date" /></label>
              <button class="ghost-button compact" @click="scanAll">↻ 刷新素材</button>
              <button class="ghost-button compact" :disabled="busy" @click="addSource">＋ 添加来源</button>
            </section>

            <section v-if="isPhysicalLocation && childFolders.length" class="workspace-folder-section">
              <div class="workspace-section-label"><strong>子文件夹</strong><span>{{ childFolders.length }} 个</span></div>
              <div class="workspace-folder-grid">
                <button v-for="folder in childFolders" :key="`${folder.source_id}:${folder.path}`" @click="enterFolder(folder)">
                  <span class="workspace-folder-icon">▰</span>
                  <p><strong>{{ folder.name }}</strong><small>{{ folder.direct_asset_count }} 个直属素材 · 共 {{ folder.asset_count }} 个</small></p>
                  <i>{{ folder.has_children ? '含子文件夹' : '打开' }} →</i>
                </button>
              </div>
            </section>

            <section class="organize-toolbar workspace-organize-toolbar">
              <label><input v-model="filters.dedupe" type="checkbox" /> 折叠已确认相同的副本</label>
              <span v-if="hiddenAssets">当前范围已折叠 {{ hiddenAssets }} 个副本</span>
              <span v-else-if="duplicates.hidden_copies">全库有 {{ duplicates.hidden_copies }} 个已确认的重复副本</span>
            </section>

            <section v-if="selectedIds.length" class="batch-bar">
              <strong>已选 {{ selectedIds.length }} 条</strong>
              <select v-model="batchLifecycleStage" aria-label="批量素材状态"><option value="">选择素材状态</option><option v-for="stage in lifecycleStages" :key="stage.id" :value="stage.id">{{ stage.label }}</option></select>
              <button :disabled="!batchLifecycleStage" @click="batchSetLifecycleStage">批量修改状态</button>
              <button @click="batchTag">批量加标签</button><button @click="packSelected">打成素材包</button><button v-if="filters.status === 'candidate' && filters.category" @click="confirmSelectedCandidates">确认“{{ filters.category }}”</button><button @click="selectedIds = []">取消选择</button>
            </section>

            <section
              v-if="assets.length"
              class="asset-grid"
              :class="{ 'list-view': assetViewMode === 'list', 'waterfall-view': assetViewMode === 'grid', loading: pageLoading }"
              :style="assetViewMode === 'grid' ? { '--waterfall-columns': waterfallColumnCount } : undefined"
            >
              <article v-for="asset in assets" :key="asset.id" class="asset-card" :class="{ missing: asset.is_missing, selected: selectedIds.includes(asset.id) }">
                <div class="asset-visual" :style="{ '--asset-ratio': assetPreviewRatio(asset) }" @click="openAsset(asset)">
                  <img v-if="shouldLoadThumbnail(asset)" :src="thumbUrl(asset)" :alt="assetName(asset)" loading="lazy" />
                  <span class="type-pill">{{ typeName(asset.media_type) }}</span>
                  <span v-if="cardMeta(asset)" class="duration-pill">{{ cardMeta(asset) }}</span>
                  <span v-if="asset.is_missing" class="missing-cover">原文件已移动或不存在</span>
                </div>
                <div class="asset-body">
                  <span class="lifecycle-stage-badge" :data-stage="asset.lifecycle_stage">{{ assetLifecycleStageLabel(asset.lifecycle_stage) }}</span>
                  <div class="asset-title-row"><button class="asset-name" @click="openAsset(asset)">{{ assetName(asset) }}</button><button class="heart" :class="{ on: asset.favorite }" @click="toggleFavorite(asset)">♥</button></div>
                  <p>{{ asset.source_name }}<template v-if="assetFolder(asset)"> / {{ assetFolder(asset) }}</template> · {{ formatBytes(asset.size) }}</p>
                  <div class="mini-tags">
                    <span v-for="category in confirmedCategories(asset).slice(0, 2)" :key="category.name">{{ category.name }}</span>
                    <span v-for="tag in asset.tags.slice(0, 1)" :key="tag" class="plain">#{{ tag }}</span>
                    <b v-if="asset.display_name_status === 'needs_review'">名称待确认</b>
                    <b v-if="asset.exact_duplicate_count" class="duplicate exact">可清理 {{ asset.exact_duplicate_count }} 个完全相同副本</b>
                    <b v-else-if="asset.suspected_duplicate_count" class="duplicate">疑似重复 {{ asset.suspected_duplicate_count }}</b>
                  </div>
                  <div class="card-actions"><label><input type="checkbox" :checked="selectedIds.includes(asset.id)" @change="toggleSelect(asset.id)" />选择</label><button @click="reveal(asset)">{{ standalone ? "定位" : "Finder" }}</button><button @click="openAsset(asset)">预览</button></div>
                </div>
              </article>
            </section>
            <nav v-if="totalAssets" class="asset-pagination" aria-label="素材分页">
              <span class="page-summary">{{ pageRangeLabel }}</span>
              <button :disabled="pagination.page === 1 || pageLoading" aria-label="上一页" @click="goToPage(pagination.page - 1)">‹</button>
              <template v-for="item in pagination.items" :key="item">
                <span v-if="typeof item === 'string'" class="page-ellipsis">…</span>
                <button
                  v-else
                  :class="{ active: item === pagination.page }"
                  :aria-current="item === pagination.page ? 'page' : undefined"
                  :disabled="pageLoading"
                  @click="goToPage(item)"
                >{{ item }}</button>
              </template>
              <button :disabled="pagination.page === pagination.pageCount || pageLoading" aria-label="下一页" @click="goToPage(pagination.page + 1)">›</button>
            </nav>
            <section v-if="!assets.length && !childFolders.length" class="empty-state"><span>□</span><h2>这里还没有素材</h2><p>可以换个筛选条件，或添加一个素材文件夹。</p><button class="primary-button" @click="addSource">添加来源</button></section>
            <p v-else-if="!assets.length && childFolders.length" class="folder-only-note">当前层没有直属素材，可以继续进入上面的子文件夹。</p>
          </div>
      </template>

      <template v-else-if="view === 'settings'">
        <section class="settings-grid">
          <div class="settings-card wide">
            <div class="settings-head"><div><h2>素材来源</h2><p>{{ standalone ? "添加要管理的文件夹，移除来源只删索引。" : "常用个人目录自动加入；其他文件夹可手动添加，移除只删索引。" }}</p></div><button class="primary-button" @click="addSource">＋ 添加文件夹</button></div>
            <div class="source-list">
              <div v-for="source in sources" :key="source.id" class="source-row">
                <span class="folder-icon">⌑</span>
                <div><strong>{{ source.name }}</strong><p>{{ source.root_path }}</p><small>最近读取：{{ source.last_scan_at ? new Date(source.last_scan_at * 1000).toLocaleString() : '尚未读取' }}</small></div>
                <span class="status-badge" :class="source.status">{{ source.status === 'ready' ? '正常' : source.status }}</span>
                <button @click="api.post('/api/scans', { source_ids: [source.id] }).then(refresh).catch(showError)">刷新</button>
                <button class="danger-text" @click="removeSource(source)">移除索引</button>
              </div>
            </div>
          </div>

          <div class="settings-card wide scan-safety-card">
            <div class="settings-head"><div><h2>最近一次素材刷新</h2><p>无法完整读取时不会把原记录当成失效；数量异常时必须由你确认。</p></div><button class="ghost-button" @click="scanAll">重新扫描</button></div>
            <dl v-if="latestScanBatch" class="scan-summary">
              <div><dt>本轮来源</dt><dd>{{ latestScanBatch.scans.length }} 个</dd></div>
              <div><dt>等待确认</dt><dd>{{ latestScanBatch.reviewScans.length }} 个来源</dd></div>
              <div><dt>拟失效</dt><dd>{{ latestScanBatch.proposedMissing }} 条</dd></div>
              <div><dt>读取问题</dt><dd>{{ latestScanBatch.errorCount }} 处</dd></div>
            </dl>
            <p v-else class="scan-empty">还没有扫描记录。</p>
            <div v-if="latestScanBatch" class="scan-source-results">
              <article v-for="scan in latestScanBatch.scans" :key="scan.id" class="scan-source-result">
                <header>
                  <strong>{{ scan.sourceName }}</strong>
                  <span>{{ scan.status === 'completed' ? '已完成' : scan.status === 'running' ? '正在读取' : scan.status === 'failed' ? '扫描未完成' : scan.status }}</span>
                  <span>{{ scan.commit_status === 'committed' ? '索引已更新' : scan.commit_status === 'review_required' ? '等待你确认' : '已跳过，原索引未变' }}</span>
                </header>
                <div v-if="scan.enumeration_errors.length" class="scan-errors">
                  <article v-for="(item, index) in scan.enumeration_errors" :key="`${scan.id}:${item.path}:${index}`">
                    <strong>{{ item.status === 'permission_required' ? '需要 macOS 访问权限' : '这个位置暂时无法读取' }}</strong>
                    <span>{{ item.path || '素材来源' }}</span>
                    <small>{{ item.message }}</small>
                  </article>
                </div>
                <div v-if="scan.commit_status === 'review_required'" class="settings-actions review-actions">
                  <div>
                    <strong>确认前请核对这 {{ scan.proposedMissing }} 条</strong>
                    <ul class="review-candidates">
                      <li v-for="candidate in scan.missing_candidates" :key="candidate.asset_id">
                        <code>{{ candidate.relative_path }}</code><small>{{ candidate.asset_id }}</small>
                      </li>
                    </ul>
                  </div>
                  <button class="danger-button" :disabled="busy" @click="confirmMissingReview(scan)">确认这个来源的失效索引</button>
                </div>
              </article>
            </div>
            <div v-if="!standalone && latestScanBatch?.hasPermissionError" class="permission-help">
              <strong>一次授权并重新扫描</strong>
              <p>点击只会在 Finder 定位 LaunchAgent 实际使用的后台程序，并打开 macOS 隐私设置，不代表已授权。请手动把下方实际后台程序加入“完全磁盘访问权限”，返回后再点“重新扫描”。</p>
              <code v-if="privacyProgramPath">{{ privacyProgramPath }}</code>
              <button class="primary-button" :disabled="busy" @click="openPrivacySettings">定位实际后台程序并打开隐私设置</button>
            </div>
          </div>

          <div class="settings-card wide recovery-card">
            <div class="settings-head"><div><h2>恢复误标为失效的索引</h2><p>先预览可恢复和拒绝数量，再由你第二次确认。只改索引，不改原文件。</p></div><button class="ghost-button" :disabled="busy" @click="previewMissingRecovery">预览可恢复结果</button></div>
            <div v-if="recoveryPreview" class="recovery-preview">
              <p><strong>{{ recoveryPreview.dry_run ? '预览结果' : '恢复结果' }}</strong><span>可恢复 {{ recoveryPreview.dry_run ? recoveryPreview.would_restore : recoveryPreview.restored }} 条 · 拒绝 {{ recoveryPreview.rejected?.length || 0 }} 条</span></p>
              <button v-if="recoveryPreview.dry_run && recoveryPreview.would_restore" class="primary-button" :disabled="busy" @click="commitMissingRecovery">再次确认并恢复索引</button>
              <details v-if="recoveryPreview.rejected?.length"><summary>查看拒绝原因</summary><ul><li v-for="item in recoveryPreview.rejected" :key="item.id">{{ item.relative_path }}：{{ item.reason }}</li></ul></details>
            </div>
          </div>

          <div v-if="!standalone" class="settings-card">
            <h2>重复素材校验</h2><p>疑似重复必须读取完整文件并核对 SHA-256。确认相同后，可在素材详情中选定保留件，再把其他原文件移入 Mac 废纸篓。</p>
            <dl><div><dt>待校验</dt><dd>{{ duplicates.pending_assets || 0 }}</dd></div><div><dt>确认重复组</dt><dd>{{ duplicates.exact_groups || 0 }}</dd></div><div><dt>可清理副本</dt><dd>{{ duplicates.hidden_copies || 0 }}</dd></div><div><dt>可释放空间</dt><dd>{{ formatBytes(duplicates.reclaimable_bytes || 0) }}</dd></div><div><dt>失败</dt><dd>{{ duplicates.failed_assets || 0 }}</dd></div></dl>
            <button v-if="duplicates.status === 'idle'" class="primary-button" @click="startDuplicateVerification">开始完整校验</button>
            <button v-else class="ghost-button" @click="toggleDuplicatePause">{{ duplicates.status === 'paused' ? '继续校验' : '暂停校验' }}</button>
          </div>
          <div class="settings-card">
            <h2>浏览器点选收集</h2><p>在 Chrome 加载收集器，然后在扩展设置粘贴下方配对令牌。按住 Windows 的 Alt 或 macOS 的 Option 点选素材，也可以点扩展图标。</p>
            <label class="token-field"><span>配对令牌</span><input :value="captureToken" readonly @focus="$event.target.select()" /></label>
          </div>
          <div v-if="standalone" class="settings-card">
            <h2>退出素材库</h2>
            <button class="ghost-button" @click="stopStandaloneLibrary">退出素材库</button>
          </div>
          <div v-else class="settings-card danger-card">
            <h2>后台服务</h2><p>素材库随 Mac 登录自动运行，异常退出会自动恢复。重启不会修改素材和索引。</p>
            <button class="ghost-button" @click="restartService">重启素材库服务</button>
          </div>
        </section>
      </template>
      </MaterialWorkspace>
    </main>

    <AssetDetails
      v-if="selected" :key="selected.id" :selected="selected" :editor="editor"
      :categories="categories" :collections="collections" :lifecycle-stages="lifecycleStages"
      :duplicate-copies="duplicateCopies" :busy="busy"
      :standalone="standalone"
      @close="closeAsset" @reveal="reveal" @toggle-favorite="toggleFavorite"
      @relocate="relocateAsset" @remove-index="removeAssetIndex"
      @trash-duplicates="trashDuplicateCopies" @open-asset="openAsset"
      @confirm-tag="({ asset, tag }) => confirmTagCandidate(asset, tag)"
      @save="saveEditor" @error="showError"
    />

    <CaptureEditor
      ref="captureEditorView"
      :capture="selectedCapture"
      :editor="captureEditor"
      :categories="captureCategories"
      :busy="busy"
      :repairing="captureRepairing"
      :saving="captureSavingId === selectedCapture?.id"
      :preview-error="capturePreviewError"
      :preview-state="capturePreviewState"
      :preview-has-audio="capturePreviewHasAudio"
      :preview-sound-enabled="capturePreviewSoundEnabled"
      :preview-generation="capturePreviewGeneration"
      @close="closeCaptureEditor"
      @toggle-favorite="toggleCaptureFavorite"
      @toggle-category="setCaptureCategory"
      @delete="deleteCapture"
      @copy-page="copyCaptureLink"
      @refresh-preview="refreshCapturePreview"
      @retry-preview="retryCapturePreview"
      @refresh-thumbnail="refreshCaptureThumbnail"
      @save-local="saveCaptureLocal"
      @copy-media="copyCaptureMediaLink"
      @save="saveCaptureEditor"
      @video-play="startCaptureAudioTrack"
      @video-pause="pauseCaptureAudioTrack"
      @video-seeked="syncCaptureAudioTrack({ force: true })"
      @video-timeupdate="syncCaptureAudioTrack()"
      @video-ratechange="syncCaptureAudioTrack({ force: true })"
      @video-volumechange="syncCaptureAudioTrack()"
      @toggle-sound="toggleCapturePreviewSoundControl()"
      @preview-error="handleCapturePreviewError"
      @update-field="updateCaptureEditorField"
    />

    <div v-if="capturePurposeManagerOpen" class="modal-backdrop capture-purpose-backdrop" @click.self="capturePurposeManagerOpen = false">
      <section class="capture-purpose-manager" role="dialog" aria-modal="true" aria-labelledby="capture-purpose-title">
        <button class="modal-close" aria-label="关闭链接用途管理" @click="capturePurposeManagerOpen = false">×</button>
        <p class="eyebrow">链接素材专用</p>
        <h2 id="capture-purpose-title">管理链接用途</h2>
        <p>这里的用途只整理网页链接，与本机素材用途彼此独立。</p>
        <form class="capture-purpose-create" @submit.prevent="createCapturePurpose">
          <input v-model.trim="capturePurposeDraft" maxlength="40" placeholder="例如：开头钩子、运镜参考、待复刻" />
          <button class="primary-button" :disabled="busy || !capturePurposeDraft.trim()">创建用途</button>
        </form>
        <div class="capture-purpose-list">
          <article v-for="category in captureCategories" :key="category.id" class="capture-purpose-row">
            <div><strong>{{ category.name }}</strong><span>{{ category.count || 0 }} 张链接卡</span></div>
            <template v-if="category.protected"><small>系统用途</small></template>
            <template v-else>
              <input v-model="capturePurposeNames[category.id]" maxlength="40" :aria-label="`重命名 ${category.name}`" />
              <button class="ghost-button" :disabled="busy || !capturePurposeNames[category.id]?.trim() || capturePurposeNames[category.id]?.trim() === category.name" @click="renameCapturePurpose(category)">保存名称</button>
              <select v-if="Number(category.count || 0) > 0" v-model="capturePurposeReplacements[category.id]" :aria-label="`删除 ${category.name} 前迁移到`">
                <option value="">删除前先选择迁移用途</option>
                <option v-for="target in captureCategories.filter((item) => item.id !== category.id)" :key="target.id" :value="target.id">{{ target.name }}</option>
              </select>
              <button class="danger-button" :disabled="busy || (Number(category.count || 0) > 0 && !capturePurposeReplacements[category.id])" @click="deleteCapturePurpose(category)">删除用途</button>
            </template>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.media-tools-notice {
  margin: 0;
  padding: 8px 16px;
  border-bottom: 1px solid var(--line);
}
</style>
