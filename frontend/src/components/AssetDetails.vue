<script setup>
import { computed, reactive, ref } from "vue";
import { clampMediaTime, duplicateCleanupSummary, filename, formatBytes, formatDuration } from "../utils.js";

const props = defineProps({
  selected: { type: Object, required: true },
  editor: { type: Object, required: true },
  categories: { type: Array, default: () => [] },
  collections: { type: Array, default: () => [] },
  lifecycleStages: { type: Array, default: () => [] },
  standalone: Boolean,
  duplicateCopies: { type: Array, default: () => [] },
  busy: Boolean,
});
const emit = defineEmits(["close", "reveal", "toggle-favorite", "relocate", "remove-index", "trash-duplicates", "open-asset", "confirm-tag", "save", "error"]);
// App keys this detail by asset ID: each asset starts with its own playback state.
const videoPlayer = ref(null);
const playback = reactive({ current: 0, duration: Number(props.selected.duration) || 0, paused: true });
const playbackPercent = computed(() => playback.duration > 0 ? Math.min(100, (playback.current / playback.duration) * 100) : 0);
const duplicateCleanup = computed(() => duplicateCleanupSummary(props.selected, props.duplicateCopies));


function syncVideoState(event) {
  const video = event.currentTarget;
  playback.current = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  playback.duration = Number.isFinite(video.duration) ? video.duration : Number(props.selected?.duration) || 0;
  playback.paused = video.paused;
}

function seekVideo(event) {
  const video = videoPlayer.value;
  if (!video) return;
  const target = clampMediaTime(event.currentTarget.value, video.duration || playback.duration);
  video.currentTime = target;
  playback.current = target;
}

async function toggleVideoPlayback() {
  const video = videoPlayer.value;
  if (!video) return;
  if (video.paused) {
    await video.play().catch((reason) => emit("error", reason));
  } else {
    video.pause();
  }
}

function previewUrl(asset) {
  return `/api/assets/${asset.id}/preview`;
}

function typeName(type) {
  return { video: "视频", image: "图片", audio: "音频" }[type] || type;
}

function assetName(asset) {
  return asset.display_name || filename(asset.relative_path);
}
</script>

<template>
    <div v-if="selected" class="modal-backdrop" @click.self="emit('close')">
      <section class="asset-modal">
        <button class="modal-close" @click="emit('close')">×</button>
        <div class="preview-panel">
          <div v-if="selected.media_type === 'video'" class="video-player">
            <video
              :key="selected.id"
              ref="videoPlayer"
              :src="previewUrl(selected)"
              controls
              autoplay
              playsinline
              @loadedmetadata="syncVideoState"
              @durationchange="syncVideoState"
              @timeupdate="syncVideoState"
              @play="syncVideoState"
              @pause="syncVideoState"
              @ended="syncVideoState"
            ></video>
            <div class="video-transport">
              <button type="button" :aria-label="playback.paused ? '播放视频' : '暂停视频'" @click="toggleVideoPlayback">{{ playback.paused ? '▶' : 'Ⅱ' }}</button>
              <span>{{ formatDuration(playback.current) }}</span>
              <input
                aria-label="视频进度"
                type="range"
                min="0"
                :max="playback.duration || selected.duration || 0"
                step="0.05"
                :value="playback.current"
                :disabled="playback.duration <= 0"
                :style="{ '--played': `${playbackPercent}%` }"
                @input="seekVideo"
                @change="seekVideo"
              />
              <span>{{ formatDuration(playback.duration || selected.duration) }}</span>
            </div>
          </div>
          <audio v-else-if="selected.media_type === 'audio'" :src="previewUrl(selected)" controls autoplay></audio>
          <img v-else :src="previewUrl(selected)" :alt="assetName(selected)" />
          <div class="preview-footer"><span>{{ typeName(selected.media_type) }} · {{ formatBytes(selected.size) }}</span><button @click="emit('reveal', selected)">{{ standalone ? "定位原文件" : "在 Finder 中显示" }}</button></div>
        </div>
        <div class="detail-panel">
          <p class="eyebrow">素材详情</p>
          <div class="detail-title"><h2>{{ assetName(selected) }}</h2><button class="heart large" :class="{ on: selected.favorite }" @click="emit('toggle-favorite', selected)">♥</button></div>
          <p class="path-copy">{{ selected.source_name }} / {{ selected.relative_path }}</p>

          <div v-if="selected.is_missing" class="missing-alert">原文件已移动或不存在。标签和备注已保留。<span><button v-if="!standalone" @click="emit('relocate', selected)">重新定位</button><button @click="emit('remove-index', selected)">只移除索引</button></span></div>

          <div v-if="!standalone && selected.exact_duplicate_count" class="duplicate-box">
            <div class="duplicate-box-heading"><span><strong>同一内容共 {{ duplicateCopies.length }} 份原文件</strong><small>当前这份作为保留件，清理前还会重新读取全部内容校验</small></span><button class="duplicate-trash-button" :disabled="busy" @click="emit('trash-duplicates')">把另外 {{ duplicateCleanup.copyCount }} 份移入废纸篓</button></div>
            <article v-for="copy in duplicateCopies" :key="copy.id" :class="{ keeper: copy.id === selected.id }"><p><b>{{ copy.source_name }}</b><span>{{ copy.relative_path }}</span></p><em v-if="copy.id === selected.id">保留这份</em><button v-else @click="emit('open-asset', copy)">改为保留</button><button @click="emit('reveal', copy)">Finder</button></article>
          </div>

          <div v-if="selected.candidate_tags?.length" class="candidate-box tag-candidates">
            <div><strong>历史标签候选</strong><small>同名唯一匹配，仍需你确认</small></div>
            <article v-for="candidate in selected.candidate_tags" :key="candidate.tag">
              <p><b>#{{ candidate.tag }}</b><span>{{ candidate.evidence }}</span></p><button @click="emit('confirm-tag', { asset: selected, tag: candidate.tag })">确认</button>
            </article>
          </div>

          <label class="field"><span>显示名称（只改素材库，不改原文件）</span><input v-model.trim="editor.display_name" maxlength="160" placeholder="给这条素材起一个能看懂的名字" /></label>
          <label class="field"><span>素材状态（只能选一个）</span><select v-model="editor.lifecycle_stage"><option v-for="stage in lifecycleStages" :key="stage.id" :value="stage.id">{{ stage.label }}</option></select></label>
          <label class="field"><span>用途（可多选）</span><div class="category-checks"><label v-for="category in categories" :key="category.name"><input v-model="editor.categories" type="checkbox" :value="category.name" />{{ category.name }}</label></div></label>
          <label class="field"><span>标签</span><input v-model="editor.tags" placeholder="用逗号分隔，例如：人物，运镜，待剪" /></label>
          <label class="field"><span>备注</span><textarea v-model="editor.note" rows="3" placeholder="记下为什么收藏、准备怎么用…"></textarea></label>
          <label v-if="collections.length" class="field"><span>加入集合</span><div class="collection-checks"><label v-for="item in collections" :key="item.id"><input v-model="editor.collections" type="checkbox" :value="item.id" />{{ item.name }}</label></div></label>
          <div class="detail-actions"><button class="primary-button" :disabled="busy" @click="emit('save')">保存修改</button></div>
        </div>
      </section>
    </div>
</template>
