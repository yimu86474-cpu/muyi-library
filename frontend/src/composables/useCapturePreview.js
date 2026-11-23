import { computed, nextTick, reactive, ref } from "vue";
import { api } from "../api.js";
import { captureDisplayTitle, captureCanUseExistingDouyinPreview, captureCanRefreshRemotePreview, captureNeedsRemoteRefresh, capturePreviewUrl, capturePreviewMode, startCapturePlayback, createCapturePreviewSessionController } from "../utils.js";
import { useCapturePlayback, isManagedCapturePreview } from "./useCapturePlayback.js";

export function useCapturePreview({ captures, showError, showNotice }) {
  const selectedCapture = ref(null);
  const captureEditorView = ref(null);
  const captureEditor = reactive({ title: "", categories: [], tags: "", note: "" });
  const capturePreviewError = ref("");
  const capturePreviewState = ref(null);
  const capturePreviewGeneration = ref({ captureId: "", actionId: 0, key: "idle:0" });
  const captureRepairing = ref(false);
  const playback = useCapturePlayback({ captureEditorView, selectedCapture, capturePreviewError });
  const { capturePreviewSoundEnabled, clearCapturePlaybackSources, destroyCaptureHls, setupCaptureAudioPreview, setupCaptureVideoPreview } = playback;
  let capturePreviewPollTimer = null;
  let capturePreviewActionId = 0;
  let capturePreviewAutoRetried = false;
  const CAPTURE_PREVIEW_POLL_INTERVAL_MS = 1000;
  const CAPTURE_PREVIEW_TIMEOUT_MS = 125000;
  const capturePreviewSession = createCapturePreviewSessionController({
    setTimer: (callback, delay) => window.setTimeout(callback, delay),
    clearTimer: (timer) => window.clearTimeout(timer),
    timeoutMs: CAPTURE_PREVIEW_TIMEOUT_MS,
  });
  const capturePreviewHasAudio = computed(() => (
    capturePreviewState.value?.state === "ready" && Boolean(capturePreviewState.value?.has_audio)
  ));

  function clearCapturePreviewPoll() {
    if (capturePreviewPollTimer !== null) {
      window.clearTimeout(capturePreviewPollTimer);
      capturePreviewPollTimer = null;
    }
  }

  function adoptCapturePreviewGeneration(token) {
    capturePreviewActionId = Number(token?.actionId) || 0;
    capturePreviewGeneration.value = { ...token };
  }

  function capturePreviewActionMatches(capture, actionId) {
    if (actionId !== capturePreviewActionId) return false;
    if (selectedCapture.value?.id !== capture.id) return false;
    return capturePreviewSession.isCurrent({ captureId: capture.id, actionId });
  }

  function armCapturePreviewDeadline(capture, token) {
    capturePreviewSession.armDeadline(token, () => {
      if (selectedCapture.value?.id !== capture.id) return;
      adoptCapturePreviewGeneration(capturePreviewSession.snapshot());
      clearCapturePreviewPoll();
      clearCapturePlaybackSources();
      capturePreviewState.value = {
        capture_id: capture.id,
        state: "needs_activation",
        has_audio: false,
        retry_after_ms: 0,
      };
      updateVisibleCapturePreviewState(capture.id, "needs_activation");
      capturePreviewError.value = "后台准备超过两分钟，可点击重新准备预览。";
    });
  }

  function updateVisibleCapturePreviewState(captureId, state) {
    const index = captures.value.findIndex((item) => item.id === captureId);
    if (index >= 0) {
      captures.value[index] = { ...captures.value[index], media_refresh_status: state };
    }
    if (selectedCapture.value?.id === captureId) {
      selectedCapture.value = { ...selectedCapture.value, media_refresh_status: state };
    }
  }

  function applyCapturePreviewResponse(capture, response, token) {
    if (!capturePreviewActionMatches(capture, token.actionId)) return false;
    const allowedStates = ["ready", "needs_activation", "resolving", "needs_login", "unavailable"];
    const state = allowedStates.includes(response?.state) ? response.state : "needs_activation";
    capturePreviewState.value = {
      capture_id: capture.id,
      state,
      has_audio: Boolean(response?.has_audio),
      retry_after_ms: Math.max(0, Number(response?.retry_after_ms) || 0),
    };
    if (state !== "ready" && state !== "resolving") capturePreviewError.value = response?.message || "";
    else capturePreviewError.value = "";
    updateVisibleCapturePreviewState(capture.id, state);
    if (state !== "resolving") capturePreviewSession.clearDeadline(token);
    return true;
  }

  async function openCaptureEditor(capture) {
    const token = capturePreviewSession.open(capture.id);
    adoptCapturePreviewGeneration(token);
    capturePreviewAutoRetried = false;
    clearCapturePreviewPoll();
    clearCapturePlaybackSources();
    capturePreviewError.value = "";
    capturePreviewSoundEnabled.value = false;
    selectedCapture.value = capture;
    captureEditor.title = captureDisplayTitle(capture);
    captureEditor.categories = [...(capture.categories || [])];
    captureEditor.tags = (capture.tags || []).join("，");
    captureEditor.note = capture.note || "";
    capturePreviewState.value = isManagedCapturePreview(capture)
      ? {
        capture_id: capture.id,
        state: capture.media_refresh_status || "needs_activation",
        has_audio: Boolean(capture.audio_url),
        retry_after_ms: 0,
      }
      : null;

    if (isManagedCapturePreview(capture)) {
      await nextTick();
      if (captureCanUseExistingDouyinPreview(capture)) {
        await loadPreparedCapturePreview(
          capture,
          { state: "ready", has_audio: Boolean(capture.audio_url) },
          token,
          0,
        );
        return;
      }
      armCapturePreviewDeadline(capture, token);
      await prepareCapturePreview(capture, { token, force: false, resumeTime: 0 });
      return;
    }

    if (!isManagedCapturePreview(capture)) {
      await nextTick();
      if (!capturePreviewActionMatches(capture, token.actionId)) return;
      const player = captureEditorView.value?.getVideoPlayer?.();
      const previewUrl = capturePreviewUrl(capture);
      const previewMode = capturePreviewMode(capture);
      let directPlayback = null;
      if (player && capture.content_kind === "video" && previewMode === "direct" && previewUrl) {
        player.muted = true;
        player.src = previewUrl;
        directPlayback = startCapturePlayback(player);
      }
      setupCaptureAudioPreview(capture);
      if (previewMode !== "direct") await setupCaptureVideoPreview(capture);
      if (directPlayback) {
        directPlayback.then((started) => {
          if (!started && capturePreviewActionMatches(capture, token.actionId)) {
            capturePreviewError.value = "自动播放未启动，请点一下播放按钮。";
          }
        });
      }
      if (captureNeedsRemoteRefresh(capture)) {
        await refreshCapturePreview(capture, { quiet: true });
      }
    }
  }

  function scheduleCapturePreviewPoll(capture, token, resumeTime) {
    clearCapturePreviewPoll();
    if (!capturePreviewActionMatches(capture, token.actionId)) return;
    capturePreviewPollTimer = window.setTimeout(async () => {
      capturePreviewPollTimer = null;
      if (!capturePreviewActionMatches(capture, token.actionId)) return;
      try {
        const response = await api.get(`/api/captures/${capture.id}/preview/status`);
        if (!applyCapturePreviewResponse(capture, response, token)) return;
        if (response.state === "ready") {
          await loadPreparedCapturePreview(capture, response, token, resumeTime);
        } else if (response.state === "resolving") {
          scheduleCapturePreviewPoll(capture, token, resumeTime);
        }
      } catch (_reason) {
        if (!capturePreviewActionMatches(capture, token.actionId)) return;
        applyCapturePreviewResponse(capture, { state: "needs_activation" }, token);
        capturePreviewError.value = "暂时无法连接预览服务，可点击重试。";
      }
    }, CAPTURE_PREVIEW_POLL_INTERVAL_MS);
  }

  async function prepareCapturePreview(capture, { token, force = false, resumeTime = 0 }) {
    if (!capturePreviewActionMatches(capture, token.actionId)) return;
    capturePreviewError.value = "";
    try {
      const response = await api.post(`/api/captures/${capture.id}/preview/prepare`, { force });
      if (!applyCapturePreviewResponse(capture, response, token)) return;
      if (response.state === "ready") {
        await loadPreparedCapturePreview(capture, response, token, resumeTime);
      } else if (response.state === "resolving") {
        scheduleCapturePreviewPoll(capture, token, resumeTime);
      }
    } catch (_reason) {
      if (!capturePreviewActionMatches(capture, token.actionId)) return;
      applyCapturePreviewResponse(capture, { state: "needs_activation" }, token);
      capturePreviewError.value = "暂时无法连接预览服务，可点击重试。";
    }
  }

  async function loadPreparedCapturePreview(capture, response, token, resumeTime = 0) {
    if (!capturePreviewActionMatches(capture, token.actionId)) return;
    capturePreviewSession.clearDeadline(token);
    clearCapturePreviewPoll();
    destroyCaptureHls();
    await nextTick();
    if (!capturePreviewActionMatches(capture, token.actionId)) return;
    const player = captureEditorView.value?.getVideoPlayer?.();
    if (!player) return;
    player.pause();
    player.muted = true;
    player.src = `/api/captures/${capture.id}/media`;
    player.load();
    if (Number(resumeTime) > 0) {
      const restoreTime = () => {
        if (!capturePreviewActionMatches(capture, token.actionId)) return;
        try { player.currentTime = Number(resumeTime) || 0; } catch (_error) { /* 等待媒体就绪 */ }
      };
      if (player.readyState >= 1) restoreTime();
      else player.addEventListener("loadedmetadata", restoreTime, { once: true });
    }
    setupCaptureAudioPreview(capture, { hasAudio: Boolean(response?.has_audio) });
    const started = await startCapturePlayback(player);
    if (!started && capturePreviewActionMatches(capture, token.actionId)) {
      capturePreviewError.value = "自动播放未启动，请点一下播放按钮。";
    }
  }

  function retryCapturePreview() {
    const capture = selectedCapture.value;
    if (!capture || !isManagedCapturePreview(capture)) return;
    const player = captureEditorView.value?.getVideoPlayer?.();
    const resumeTime = Number(player?.currentTime || 0);
    const retry = capturePreviewSession.manualRetry(capture.id);
    if (!retry) return;
    adoptCapturePreviewGeneration(retry.token);
    clearCapturePreviewPoll();
    clearCapturePlaybackSources();
    applyCapturePreviewResponse(capture, { state: "resolving" }, retry.token);
    armCapturePreviewDeadline(capture, retry.token);
    void prepareCapturePreview(capture, { token: retry.token, force: true, resumeTime });
  }

  function showCapturePreviewPlaybackFailure(message) {
    capturePreviewError.value = message || "这条预览暂时无法播放，可手动重试。";
  }

  async function handleCapturePreviewError(payload) {
    const capture = selectedCapture.value;
    const message = typeof payload === "string" ? payload : payload?.message;
    if (!capturePreviewSession.isCurrent(payload)) return;
    if (!isManagedCapturePreview(capture)) {
      showCapturePreviewPlaybackFailure(message);
      return;
    }
    if (capturePreviewAutoRetried) return showCapturePreviewPlaybackFailure("自动换新后仍无法播放，可手动重试。");
    const retry = capturePreviewSession.retryFromVideoError(payload);
    if (!retry) return;
    capturePreviewAutoRetried = true;
    const resumeTime = Number(payload?.currentTime || captureEditorView.value?.getVideoPlayer?.()?.currentTime || 0);
    adoptCapturePreviewGeneration(retry.token);
    clearCapturePreviewPoll();
    clearCapturePlaybackSources();
    applyCapturePreviewResponse(capture, { state: "resolving" }, retry.token);
    armCapturePreviewDeadline(capture, retry.token);
    await prepareCapturePreview(capture, { token: retry.token, force: true, resumeTime });
  }

  async function refreshCapturePreview(capture, { quiet = false } = {}) {
    if (!captureCanRefreshRemotePreview(capture) || captureRepairing.value) return;
    captureRepairing.value = true;
    capturePreviewError.value = "";
    try {
      const updated = await api.post(`/api/captures/${capture.id}/refresh-media`);
      const index = captures.value.findIndex((item) => item.id === updated.id);
      if (index >= 0) captures.value[index] = updated;
      if (selectedCapture.value?.id === updated.id) {
        selectedCapture.value = updated;
        await nextTick();
        setupCaptureAudioPreview(updated);
        await setupCaptureVideoPreview(updated);
      }
      if (!quiet) showNotice("已补全真实预览地址，没有下载视频");
    } catch (reason) {
      capturePreviewError.value = reason?.message || String(reason);
      if (!quiet) showError(reason);
    } finally {
      captureRepairing.value = false;
    }
  }

  function closeCaptureEditor() {
    adoptCapturePreviewGeneration(capturePreviewSession.close());
    clearCapturePreviewPoll();
    clearCapturePlaybackSources();
    capturePreviewAutoRetried = false;
    capturePreviewState.value = null;
    capturePreviewError.value = "";
    capturePreviewSoundEnabled.value = false;
    selectedCapture.value = null;
    captureEditor.title = "";
    captureEditor.categories = [];
    captureEditor.tags = "";
    captureEditor.note = "";
  }

  return {
    selectedCapture, captureEditorView, captureEditor,
    capturePreviewError, capturePreviewState, capturePreviewGeneration,
    captureRepairing, capturePreviewHasAudio, capturePreviewSoundEnabled,
    openCaptureEditor, closeCaptureEditor, retryCapturePreview,
    handleCapturePreviewError, refreshCapturePreview, startCaptureAudioTrack: playback.startCaptureAudioTrack,
    pauseCaptureAudioTrack: playback.pauseCaptureAudioTrack, syncCaptureAudioTrack: playback.syncCaptureAudioTrack, toggleCapturePreviewSoundControl: playback.toggleCapturePreviewSoundControl,
  };
}
