import { ref } from "vue";
import { capturePreviewUrl, capturePreviewMode, startCapturePlayback, syncCapturePreviewSound, toggleCapturePreviewSound, capturePreviewFailureMessage } from "../utils.js";

export function isManagedCapturePreview(capture) {
  return ["douyin", "xiaohongshu"].includes(capture?.platform) && capture?.content_kind === "video";
}

export function useCapturePlayback({ captureEditorView, selectedCapture, capturePreviewError }) {
  const capturePreviewSoundEnabled = ref(false);
  let captureHlsPlayer = null;

  function clearCapturePlaybackSources() {
    destroyCaptureHls();
    const player = captureEditorView.value?.getVideoPlayer?.();
    if (player) {
      player.pause();
      player.removeAttribute("src");
      player.load();
    }
    const audio = captureEditorView.value?.getAudioPlayer?.();
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
  }

  function destroyCaptureHls() {
    if (captureHlsPlayer) {
      captureHlsPlayer.destroy();
      captureHlsPlayer = null;
    }
  }

  function syncCaptureAudioTrack({ force = false } = {}) {
    const video = captureEditorView.value?.getVideoPlayer?.();
    const audio = captureEditorView.value?.getAudioPlayer?.();
    if (!video || !audio || !audio.getAttribute("src")) return;
    capturePreviewSoundEnabled.value = syncCapturePreviewSound(video, audio);
    audio.playbackRate = video.playbackRate;
    const drift = Math.abs((Number(audio.currentTime) || 0) - (Number(video.currentTime) || 0));
    if (force || drift > 0.35) {
      try { audio.currentTime = Number(video.currentTime) || 0; } catch (_error) { /* 等待音轨就绪 */ }
    }
  }

  function toggleCapturePreviewSoundControl() {
    const video = captureEditorView.value?.getVideoPlayer?.();
    const audio = captureEditorView.value?.getAudioPlayer?.();
    capturePreviewSoundEnabled.value = toggleCapturePreviewSound(video, audio);
    if (capturePreviewSoundEnabled.value && video?.paused === false) startCaptureAudioTrack();
  }

  function startCaptureAudioTrack() {
    const audio = captureEditorView.value?.getAudioPlayer?.();
    if (!audio || !audio.getAttribute("src")) return;
    syncCaptureAudioTrack({ force: true });
    Promise.resolve(audio.play()).catch(() => {
      // 浏览器仍保留视频的手动播放入口；用户再次点播放时会重新同步音轨。
    });
  }

  function pauseCaptureAudioTrack() {
    captureEditorView.value?.getAudioPlayer?.()?.pause();
  }

  function setupCaptureAudioPreview(capture, { hasAudio = false } = {}) {
    const audio = captureEditorView.value?.getAudioPlayer?.();
    if (!audio) return;
    audio.pause();
    if (!isManagedCapturePreview(capture) || !hasAudio) {
      audio.removeAttribute("src");
      audio.load();
      return;
    }
    audio.src = `/api/captures/${capture.id}/audio`;
    audio.load();
    syncCaptureAudioTrack({ force: true });
    if (captureEditorView.value?.getVideoPlayer?.()?.paused === false) startCaptureAudioTrack();
  }

  async function setupCaptureVideoPreview(capture) {
    destroyCaptureHls();
    capturePreviewError.value = "";
    if (!capture || capture.content_kind !== "video") return;
    const url = capturePreviewUrl(capture);
    if (!url) return;
    const player = captureEditorView.value?.getVideoPlayer?.();
    if (!player) return;
    const previewMode = capturePreviewMode(capture);
    if (previewMode === "direct") {
      // This path is used after a pending X card has just received a real URL.
      // Existing direct cards start synchronously in openCaptureEditor instead.
      player.muted = true;
      player.src = url;
      startCapturePlayback(player).then((started) => {
        if (!started && selectedCapture.value?.id === capture.id) {
          capturePreviewError.value = "自动播放未启动，请点一下播放按钮。";
        }
      });
      return;
    }
    if (player.canPlayType("application/vnd.apple.mpegurl")) {
      player.src = url;
      await startCapturePlayback(player, { onBlocked: (reason) => {
        const code = reason?.name || "PlaybackError";
        capturePreviewError.value = `自动播放未启动（${code}），请点一下播放按钮。`;
      } });
      return;
    }
    const { default: Hls } = await import("hls.js");
    if (selectedCapture.value?.id !== capture.id || captureEditorView.value?.getVideoPlayer?.() !== player) return;
    if (!Hls.isSupported()) {
      capturePreviewError.value = "当前浏览器无法播放这条 HLS 真流，可打开原作品查看。";
      return;
    }
    captureHlsPlayer = new Hls({ enableWorker: true, lowLatencyMode: false });
    captureHlsPlayer.on(Hls.Events.ERROR, (_event, data) => {
      if (data?.fatal) capturePreviewError.value = capturePreviewFailureMessage(capture);
    });
    captureHlsPlayer.on(Hls.Events.MANIFEST_PARSED, () => {
      startCapturePlayback(player);
    });
    captureHlsPlayer.loadSource(url);
    captureHlsPlayer.attachMedia(player);
  }

  return {
    capturePreviewSoundEnabled, clearCapturePlaybackSources, destroyCaptureHls,
    syncCaptureAudioTrack, toggleCapturePreviewSoundControl, startCaptureAudioTrack,
    pauseCaptureAudioTrack, setupCaptureAudioPreview, setupCaptureVideoPreview,
  };
}
