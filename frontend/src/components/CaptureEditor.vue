<script setup>
import { computed, ref, watch } from "vue";
import {
  captureCanRefreshRemotePreview,
  captureCanRefreshThumbnail,
  captureDisplayMetadata,
  captureDisplayTitle,
  captureLocalSaveAction,
  capturePreviewMaintenanceAction,
  capturePreviewFailureMessage,
  capturePreviewPresentation,
  capturePreviewUrl,
  captureSourceWarning,
  captureThumbnailUrl,
  captureWorkPageUrl,
} from "../utils.js";

const props = defineProps({
  capture: { type: Object, default: null },
  editor: { type: Object, required: true },
  categories: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  repairing: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  previewError: { type: String, default: "" },
  previewState: { type: [String, Object], default: null },
  previewHasAudio: { type: Boolean, default: false },
  previewSoundEnabled: { type: Boolean, default: false },
  previewGeneration: { type: Object, default: () => ({ captureId: "", actionId: 0, key: "idle:0" }) },
});

const emit = defineEmits([
  "close",
  "toggle-favorite",
  "toggle-category",
  "delete",
  "copy-page",
  "refresh-preview",
  "refresh-thumbnail",
  "save-local",
  "copy-media",
  "save",
  "video-play",
  "video-pause",
  "video-seeked",
  "video-timeupdate",
  "video-ratechange",
  "video-volumechange",
  "toggle-sound",
  "preview-error",
  "retry-preview",
  "update-field",
]);

const backdrop = ref(null);
const videoPlayer = ref(null);
const audioPlayer = ref(null);
const failedImageUrl = ref("");
watch(() => [props.capture?.id, props.capture?.updated_at, props.repairing], () => {
  failedImageUrl.value = "";
});

const title = computed({
  get: () => props.editor.title,
  set: (value) => emit("update-field", { field: "title", value }),
});
const tags = computed({
  get: () => props.editor.tags,
  set: (value) => emit("update-field", { field: "tags", value }),
});
const note = computed({
  get: () => props.editor.note,
  set: (value) => emit("update-field", { field: "note", value }),
});
const isManagedVideo = computed(() => (
  ["douyin", "xiaohongshu"].includes(props.capture?.platform) && props.capture?.content_kind === "video"
));
const previewPresentation = computed(() => (
  capturePreviewPresentation(props.capture, props.previewState)
));
const previewStateName = computed(() => (
  typeof props.previewState === "string" ? props.previewState : props.previewState?.state
));
const localSaveAction = computed(() => captureLocalSaveAction(
  props.capture,
  { saving: props.saving, previewState: props.previewState },
));
const previewMaintenanceAction = computed(() => (
  capturePreviewMaintenanceAction(props.capture, props.previewState)
));
const canRefreshThumbnail = computed(() => (
  captureCanRefreshThumbnail(props.capture, props.previewState)
));
const showVideo = computed(() => (
  props.capture?.content_kind === "video"
  && (isManagedVideo.value ? previewStateName.value === "ready" : Boolean(capturePreviewUrl(props.capture)))
));
const videoGeneration = computed(() => {
  const captureId = String(props.previewGeneration?.captureId || props.capture?.id || "");
  const actionId = Number(props.previewGeneration?.actionId) || 0;
  return {
    captureId,
    actionId,
    key: String(props.previewGeneration?.key || `${captureId || "idle"}:${actionId}`),
  };
});

function reportPreviewError(event) {
  const player = event.currentTarget;
  const { captureId, actionId } = event.currentTarget.dataset;
  emit("preview-error", {
    captureId: String(captureId || ""),
    actionId: Number(actionId),
    message: capturePreviewFailureMessage(props.capture),
    currentTime: Number(player.currentTime || 0),
  });
}

defineExpose({
  getBackdrop: () => backdrop.value,
  getVideoPlayer: () => videoPlayer.value,
  getAudioPlayer: () => audioPlayer.value,
});
</script>

<template>
  <div ref="backdrop" v-show="capture" class="modal-backdrop" @click.self="emit('close')">
    <section class="capture-editor-modal">
      <template v-if="capture">
        <button class="modal-close" @click="emit('close')">×</button>
        <p class="eyebrow">链接卡片</p>
        <div class="capture-editor-title"><h2>{{ captureDisplayTitle(capture) }}</h2><button class="heart large" :class="{ on: capture.favorite }" :aria-label="capture.favorite ? '取消收藏' : '收藏链接素材'" @click="emit('toggle-favorite', capture)">♥</button></div>
        <div v-if="captureDisplayMetadata(capture).length" class="capture-editor-source"><span v-for="item in captureDisplayMetadata(capture)" :key="item.key">{{ item.key === 'author' ? `作者：${item.value}` : item.key === 'like' ? `点赞：${item.value}` : `发布：${item.value}` }}</span></div>
      </template>
      <div class="capture-link-preview">
        <span v-if="isManagedVideo" class="capture-preview-state" :class="previewPresentation.tone">{{ previewPresentation.label }}</span>
        <video ref="videoPlayer" :key="videoGeneration.key" v-show="showVideo" :data-capture-id="videoGeneration.captureId" :data-action-id="videoGeneration.actionId" :poster="captureThumbnailUrl(capture)" controls playsinline preload="auto" @play="emit('video-play')" @pause="emit('video-pause')" @seeked="emit('video-seeked')" @timeupdate="emit('video-timeupdate')" @ratechange="emit('video-ratechange')" @volumechange="emit('video-volumechange')" @error="reportPreviewError"></video>
        <audio v-if="previewHasAudio" ref="audioPlayer" preload="auto"></audio>
        <button v-if="isManagedVideo && showVideo && previewHasAudio" class="capture-native-sound-toggle" type="button" :aria-label="previewSoundEnabled ? '静音' : '开启声音'" :title="previewSoundEnabled ? '静音' : '开启声音'" @click="emit('toggle-sound')">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9v6h4l5 4V5L8 9H4Z" />
            <path v-if="previewSoundEnabled" d="M16 8.5c1.3 1.2 1.3 5.8 0 7M18.5 6c3 3 3 9 0 12" />
            <path v-else d="m16 9 5 6M21 9l-5 6" />
          </svg>
        </button>
        <img v-if="capture?.content_kind === 'image' && capturePreviewUrl(capture) && failedImageUrl !== capturePreviewUrl(capture)" :src="capturePreviewUrl(capture)" :alt="captureDisplayTitle(capture)" referrerpolicy="no-referrer" @error="failedImageUrl = capturePreviewUrl(capture)" />
        <div v-else-if="capture && isManagedVideo && previewStateName !== 'ready'" class="capture-preview-unavailable capture-preview-preparing">
          <img v-if="captureThumbnailUrl(capture)" :src="captureThumbnailUrl(capture)" :alt="captureDisplayTitle(capture)" referrerpolicy="no-referrer" />
          <p>{{ previewPresentation.label }}</p>
          <button v-if="previewPresentation.canRetry" class="ghost-button" type="button" @click="emit('retry-preview')">重新准备预览</button>
        </div>
        <div v-else-if="capture && !isManagedVideo && !(capture.content_kind === 'video' && capturePreviewUrl(capture))" class="capture-preview-unavailable">
          <img v-if="capture.content_kind !== 'image' && captureThumbnailUrl(capture)" :src="captureThumbnailUrl(capture)" :alt="captureDisplayTitle(capture)" referrerpolicy="no-referrer" />
          <p v-if="repairing">{{ capture.content_kind === 'image' ? '正在恢复图片封面…' : '正在从公开作品页补全真实预览地址，不会下载视频…' }}</p>
          <p v-else-if="capture.platform === 'xiaohongshu' && capture.content_kind === 'image'">{{ capture.thumbnail_status === 'failed' || failedImageUrl ? '图片封面加载失败，可点击下方“重新加载封面”，或打开原笔记重新采集。' : '图片封面正在准备，可点击下方“加载封面”重试。' }}</p>
          <p v-else>{{ capture.content_kind === 'video' ? '这条视频使用了只在原网页当前标签有效的地址，素材库无法脱离原页直接播放。' : '图片原地址已失效，可回原网页查看。' }}</p>
          <a v-if="captureWorkPageUrl(capture)" :href="captureWorkPageUrl(capture)" target="_blank" rel="noopener noreferrer">打开原作品 ↗</a>
          <span v-else class="capture-source-unverified">原作品地址待核验</span>
        </div>
        <p v-if="previewError" class="capture-preview-error">{{ previewError }}</p>
        <p v-if="captureSourceWarning(capture)" class="capture-source-unverified" role="status">{{ captureSourceWarning(capture) }}</p>
      </div>
      <template v-if="capture">
        <div v-if="localSaveAction.visible" class="capture-local-save" :class="localSaveAction.state">
          <div>
            <strong>{{ localSaveAction.label }}</strong>
            <p>{{ localSaveAction.description }}</p>
            <small v-if="localSaveAction.state === 'saved'">文件已保存在本机，可从素材库的采集来源查看。</small>
            <small v-if="capture.status === 'download_failed' && capture.failure_reason">失败原因：{{ capture.failure_reason }}</small>
          </div>
          <button class="primary-button" :disabled="localSaveAction.disabled || busy || repairing" @click="emit('save-local', capture)">{{ localSaveAction.label }}</button>
        </div>
        <label class="field"><span>卡片名称</span><input v-model.trim="title" maxlength="500" placeholder="给这条素材起一个能看懂的名字" /></label>
        <label class="field"><span>用途分类（可多选）</span><div class="category-checks"><label v-for="category in categories" :key="category.id"><input type="checkbox" :checked="editor.categories.includes(category.name)" @change="emit('toggle-category', category.name, $event.target.checked)" />{{ category.name }}</label></div></label>
        <label class="field"><span>标签</span><input v-model="tags" maxlength="1000" placeholder="用逗号分隔，例如：开头参考，女装，待复刻" /></label>
        <label class="field"><span>备注</span><textarea v-model="note" maxlength="4000" rows="5" placeholder="记下为什么收藏、准备怎么用、哪一段值得参考…"></textarea></label>
        <div class="detail-actions">
          <button class="danger-button capture-modal-delete" :disabled="busy || repairing || saving" @click="emit('delete', capture)">删除这张卡</button>
          <button v-if="captureWorkPageUrl(capture)" class="ghost-button" @click="emit('copy-page', capture)">复制作品页</button>
          <button v-if="!isManagedVideo && captureCanRefreshRemotePreview(capture)" class="ghost-button" :disabled="repairing" @click="emit('refresh-preview', capture)">{{ repairing ? "正在补全…" : "重新补全预览" }}</button>
          <button v-if="previewMaintenanceAction.visible" class="ghost-button" type="button" :disabled="previewMaintenanceAction.disabled || busy || repairing" @click="emit('retry-preview')">{{ previewMaintenanceAction.label }}</button>
          <button v-if="canRefreshThumbnail" class="ghost-button" :disabled="repairing || busy" @click="emit('refresh-thumbnail', capture)">{{ repairing ? "正在加载封面…" : capture.thumbnail_status === 'failed' ? "重新加载封面" : "加载封面" }}</button>
          <button v-if="/^https?:\/\//i.test(capture.media_url || '')" class="ghost-button" @click="emit('copy-media', capture)">复制媒体源地址</button>
          <button class="ghost-button" :disabled="busy || repairing || saving" @click="emit('close')">取消</button>
          <button class="primary-button" :disabled="busy || repairing || saving" @click="emit('save')">保存</button>
        </div>
      </template>
    </section>
  </div>
</template>
