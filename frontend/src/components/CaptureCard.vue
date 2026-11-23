<script setup>
import { computed, ref, watch } from "vue";
import {
  captureCanAutoRepairThumbnail,
  captureDisplayMetadata,
  captureDisplayTitle,
  captureKindLabel,
  captureLocalSaveAction,
  capturePreviewPresentation,
  captureSourceWarning,
  captureThumbnailUrl,
  captureWorkPageUrl,
} from "../utils.js";

const props = defineProps({
  capture: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  platformLabel: { type: Function, required: true },
  previewState: { type: [String, Object], default: null },
});

const emit = defineEmits(["open", "toggle-favorite", "delete", "repair-thumbnail", "save-local"]);
const imageSaveAction = computed(() => captureLocalSaveAction(props.capture, { saving: props.saving }));
const failedThumbnailUrl = ref("");
const previewPresentation = computed(() => (
  failedThumbnailUrl.value && props.capture?.content_kind === "image"
    ? { label: "封面加载失败", tone: "attention", canRetry: true }
    : capturePreviewPresentation(props.capture, props.previewState)
));
const previewBadgeLabel = computed(() => (
  previewPresentation.value.tone === "working" ? "准备中" : previewPresentation.value.label
));
const thumbnailUrl = computed(() => captureThumbnailUrl(props.capture));
const visibleThumbnailUrl = computed(() => (
  thumbnailUrl.value && thumbnailUrl.value !== failedThumbnailUrl.value
    ? thumbnailUrl.value
    : ""
));

watch(() => [thumbnailUrl.value, props.capture?.updated_at], () => {
  failedThumbnailUrl.value = "";
});

watch(
  () => [
    props.capture?.id,
    props.capture?.thumbnail_status,
    props.capture?.thumbnail_url,
  ],
  () => {
    if (captureCanAutoRepairThumbnail(props.capture)) {
      emit("repair-thumbnail", props.capture);
    }
  },
  { immediate: true },
);

function handleThumbnailError(event) {
  failedThumbnailUrl.value = String(event?.currentTarget?.currentSrc || thumbnailUrl.value || "");
  if (captureCanAutoRepairThumbnail(props.capture)) {
    emit("repair-thumbnail", props.capture);
  }
}
</script>

<template>
  <article class="capture-card">
    <button class="capture-cover" type="button" :aria-label="`预览和整理：${captureDisplayTitle(capture)}`" @click="emit('open', capture)">
      <span class="capture-cover-fallback">{{ capture.content_kind === "image" ? "▧" : "▶" }}</span>
      <img v-if="visibleThumbnailUrl" :src="visibleThumbnailUrl" :alt="captureDisplayTitle(capture)" loading="lazy" referrerpolicy="no-referrer" @error="handleThumbnailError" />
      <span v-if="!visibleThumbnailUrl" class="capture-cover-status">{{ capture.content_kind === 'image' ? previewBadgeLabel : '封面待修复' }}</span>
      <b>{{ platformLabel(capture.platform) }} · {{ captureKindLabel(capture) }}</b>
      <i class="capture-preview-badge" :class="previewPresentation.tone">{{ previewBadgeLabel }}</i>
    </button>
    <div class="capture-card-body">
      <div class="capture-title-row">
        <h2><a v-if="captureWorkPageUrl(capture)" :href="captureWorkPageUrl(capture)" target="_blank" rel="noopener noreferrer">{{ captureDisplayTitle(capture) }}</a><span v-else>{{ captureDisplayTitle(capture) }}</span></h2>
        <button class="heart" :class="{ on: capture.favorite }" :aria-label="capture.favorite ? '取消收藏' : '收藏链接素材'" @click="emit('toggle-favorite', capture)">♥</button>
      </div>
      <div v-if="captureDisplayMetadata(capture).length" class="capture-compact-meta">
        <template v-for="(item, index) in captureDisplayMetadata(capture)" :key="item.key">
          <i v-if="index">·</i>
          <span v-if="item.key === 'author'">{{ item.value.startsWith('@') ? item.value : `@${item.value}` }}</span>
          <span v-else-if="item.key === 'like'">♥ {{ item.value }}</span>
          <span v-else>{{ item.value }}</span>
        </template>
      </div>
      <div v-if="capture.categories?.length" class="capture-categories"><span v-for="category in capture.categories" :key="category">{{ category }}</span></div>
      <div v-if="capture.tags?.length" class="capture-tags"><span v-for="tag in capture.tags" :key="tag"># {{ tag }}</span></div>
      <p v-if="capture.note" class="capture-note">{{ capture.note }}</p>
      <p v-if="captureSourceWarning(capture)" class="capture-source-unverified" role="status">{{ captureSourceWarning(capture) }}</p>
      <div class="capture-card-actions">
        <a v-if="captureWorkPageUrl(capture)" :href="captureWorkPageUrl(capture)" target="_blank" rel="noopener noreferrer">{{ capture.content_kind === "image" ? "打开图片来源" : "打开原视频" }} ↗</a>
        <span v-else class="capture-source-unverified">原作品地址待核验</span>
        <button class="capture-delete-button" :disabled="busy" @click="emit('delete', capture)">删除</button>
        <button v-if="capture.content_kind === 'image' && ['available', 'saving'].includes(imageSaveAction.state)" type="button" class="capture-edit-button" :disabled="imageSaveAction.disabled || busy" @click="emit('save-local', capture)">{{ imageSaveAction.label }}</button>
        <button class="capture-edit-button" @click="emit('open', capture)">预览·整理</button>
      </div>
    </div>
  </article>
</template>
