import { reactive, ref } from "vue";
import { api } from "../api.js";

export function useCapturePurposes({
  captureCategories, captureFilters, captureEditor, busy,
  loadCaptures, showError, showNotice,
}) {
  const capturePurposeManagerOpen = ref(false);
  const capturePurposeDraft = ref("");
  const capturePurposeNames = reactive({});
  const capturePurposeReplacements = reactive({});

  async function reloadCaptureCategories() {
    const data = await api.get("/api/capture-categories");
    captureCategories.value = data.items || [];
    captureCategories.value.forEach((category) => {
      capturePurposeNames[category.id] = category.name;
    });
  }

  async function createCapturePurpose() {
    const name = capturePurposeDraft.value.trim();
    if (!name || busy.value) return;
    busy.value = true;
    try {
      await api.post("/api/capture-categories", { name });
      capturePurposeDraft.value = "";
      await reloadCaptureCategories();
      showNotice("新的链接用途已创建");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  async function renameCapturePurpose(category) {
    const name = String(capturePurposeNames[category.id] || "").trim();
    if (!name || name === category.name || busy.value) return;
    busy.value = true;
    try {
      const updated = await api.patch(`/api/capture-categories/${category.id}`, { name });
      if (captureFilters.category === category.name) captureFilters.category = updated.name;
      captureEditor.categories = captureEditor.categories.map((item) => (
        item === category.name ? updated.name : item
      ));
      await reloadCaptureCategories();
      await loadCaptures();
      showNotice("链接用途已改名，已有卡片同步更新");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  async function deleteCapturePurpose(category) {
    if (category.protected || busy.value) return;
    const replacementId = String(capturePurposeReplacements[category.id] || "");
    if (Number(category.count || 0) > 0 && !replacementId) {
      showError(new Error("这个用途仍有链接素材，请先选择迁移到哪个用途"));
      return;
    }
    if (!window.confirm(`确定删除链接用途“${category.name}”吗？原网页和本机文件都不会改变。`)) return;
    busy.value = true;
    try {
      const query = replacementId ? `?replacement_id=${encodeURIComponent(replacementId)}` : "";
      await api.delete(`/api/capture-categories/${category.id}${query}`);
      if (captureFilters.category === category.name) captureFilters.category = "";
      await reloadCaptureCategories();
      await loadCaptures({ page: 1 });
      showNotice("链接用途已删除，已有卡片完成迁移");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  function openCapturePurposeManager() {
    captureCategories.value.forEach((category) => {
      capturePurposeNames[category.id] = category.name;
    });
    capturePurposeManagerOpen.value = true;
  }

  return {
    capturePurposeManagerOpen, capturePurposeDraft, capturePurposeNames,
    capturePurposeReplacements, reloadCaptureCategories, createCapturePurpose,
    renameCapturePurpose, deleteCapturePurpose, openCapturePurposeManager,
  };
}
