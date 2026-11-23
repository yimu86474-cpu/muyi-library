import { ref } from "vue";
import { api } from "../api.js";
import { captureCanAutoRepairThumbnail, captureThumbnailRefreshSuccessMessage, nextCaptureCategories, formatBytes } from "../utils.js";

export function useCaptureActions({
  captures, selectedCapture, captureEditor, closeCaptureEditor,
  capturePreviewError, captureRepairing, busy, showError,
  showNotice, onFavoriteChanged, onDeleted,
}) {
  const captureThumbnailAutoRepairIds = new Set();
  const captureSavingId = ref("");

  async function refreshCaptureThumbnail(capture) {
    if (!capture || captureRepairing.value) return;
    captureRepairing.value = true;
    try {
      const updated = await api.post(`/api/captures/${capture.id}/refresh-thumbnail`);
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
      if (selectedCapture.value?.id === updated.id) selectedCapture.value = updated;
      showNotice(captureThumbnailRefreshSuccessMessage(updated));
    } catch (reason) {
      showError(reason);
    } finally {
      captureRepairing.value = false;
    }
  }

  async function repairCaptureThumbnailAutomatically(capture) {
    const captureId = String(capture?.id || "");
    if (!captureCanAutoRepairThumbnail(capture) || captureThumbnailAutoRepairIds.has(captureId)) return;
    captureThumbnailAutoRepairIds.add(captureId);
    try {
      const updated = await api.post(`/api/captures/${captureId}/refresh-thumbnail`);
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
      if (selectedCapture.value?.id === updated.id) selectedCapture.value = updated;
    } catch (reason) {
      const index = captures.value.findIndex((item) => item.id === captureId);
      const failure = reason?.message || String(reason);
      if (index >= 0) {
        captures.value[index] = {
          ...captures.value[index],
          thumbnail_status: "failed",
          thumbnail_error: failure,
        };
      }
      if (selectedCapture.value?.id === captureId) {
        selectedCapture.value = { ...selectedCapture.value, thumbnail_status: "failed", thumbnail_error: failure };
      }
    } finally {
      captureThumbnailAutoRepairIds.delete(captureId);
    }
  }

  async function saveCaptureLocal(capture) {
    if (!capture || captureSavingId.value) return;
    captureSavingId.value = capture.id;
    capturePreviewError.value = "";
    try {
      const updated = await api.post(`/api/captures/${capture.id}/save-local`);
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
      if (selectedCapture.value?.id === updated.id) selectedCapture.value = updated;
      if (updated.adapter?.outcome === "success") {
        showNotice(updated.message || `已校验并保存（${formatBytes(updated.adapter.byte_size)}）`);
      } else {
        const reason = updated.failure_reason || "本地保存失败，链接卡仍然保留";
        capturePreviewError.value = reason;
        showError(new Error(reason));
      }
    } catch (reason) {
      capturePreviewError.value = reason?.message || String(reason);
      showError(reason);
    } finally {
      captureSavingId.value = "";
    }
  }

  function setCaptureCategory(category, checked) {
    captureEditor.categories = nextCaptureCategories(captureEditor.categories, category, checked);
  }

  function updateCaptureEditorField({ field, value }) {
    if (!["title", "tags", "note"].includes(field)) return;
    captureEditor[field] = value;
  }

  async function saveCaptureEditor() {
    if (!selectedCapture.value || busy.value) return;
    busy.value = true;
    try {
      const tags = captureEditor.tags.split(/[，,、\n]+/).map((item) => item.trim()).filter(Boolean);
      const updated = await api.patch(`/api/captures/${selectedCapture.value.id}/metadata`, {
        page_title: captureEditor.title,
        categories: captureEditor.categories,
        tags,
        note: captureEditor.note,
      });
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
      closeCaptureEditor();
      showNotice("名称、用途分类、标签和备注已保存");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  async function toggleCaptureFavorite(capture) {
    if (!capture || busy.value) return;
    busy.value = true;
    try {
      const updated = await api.patch(`/api/captures/${capture.id}/favorite`, {
        favorite: !Boolean(capture.favorite),
      });
      if (selectedCapture.value?.id === updated.id) selectedCapture.value = updated;
      await onFavoriteChanged(updated);
      showNotice(updated.favorite ? "已收藏这条链接素材" : "已取消收藏");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  async function deleteCapture(capture) {
    if (!capture || busy.value) return;
    const confirmed = window.confirm("只删除素材库里的这张链接卡，不会删除网页视频、图片或本机原文件。确定删除吗？");
    if (!confirmed) return;
    busy.value = true;
    try {
      await api.delete(`/api/captures/${capture.id}`);
      if (selectedCapture.value?.id === capture.id) closeCaptureEditor();
      await onDeleted();
      showNotice("链接卡已删除，原网页和本机文件都没有改动");
    } catch (reason) {
      showError(reason);
    } finally {
      busy.value = false;
    }
  }

  async function copyCaptureLink(capture) {
    try {
      await navigator.clipboard.writeText(capture.page_url);
      showNotice("链接已复制");
    } catch (_error) {
      showError("复制失败，可以点击“打开原网页”后复制地址");
    }
  }

  async function copyCaptureMediaLink(capture) {
    const mediaUrl = String(capture?.media_url || "").trim();
    if (!/^https?:\/\//i.test(mediaUrl)) return showError("这条卡片还没有取得真实媒体地址");
    try {
      await navigator.clipboard.writeText(mediaUrl);
      showNotice("媒体源地址已复制；它可能会过期，本地预览不受影响");
    } catch (_error) {
      showError("媒体源地址复制失败");
    }
  }

  return {
    captureSavingId, refreshCaptureThumbnail, repairCaptureThumbnailAutomatically,
    saveCaptureLocal, setCaptureCategory, updateCaptureEditorField,
    saveCaptureEditor, toggleCaptureFavorite, deleteCapture,
    copyCaptureLink, copyCaptureMediaLink,
  };
}
