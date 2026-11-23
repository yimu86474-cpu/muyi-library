<script setup>
import { computed } from "vue";
import { folderKey } from "../utils.js";
import TreeFolderNode from "./TreeFolderNode.vue";

const props = defineProps({
  standalone: Boolean,
  activeNavigation: { type: String, default: "assets" },
  sources: { type: Array, default: () => [] },
  collections: { type: Array, default: () => [] },
  location: { type: Object, default: () => ({ kind: "all" }) },
  captureCount: { type: Number, default: 0 },
  missingCount: { type: Number, default: 0 },
  expandedKeys: { type: Array, default: () => [] },
  childrenByKey: { type: Object, default: () => ({}) },
  loadingKeys: { type: Array, default: () => [] },
  errorByKey: { type: Object, default: () => ({}) },
  drawerOpen: { type: Boolean, default: false },
});
const emit = defineEmits([
  "select",
  "toggle",
  "create-collection",
  "close",
  "open-home",
  "open-assets",
  "open-favorites",
  "open-captures",
  "open-settings",
]);

const selectedPhysicalKey = computed(() => {
  if (!['source', 'folder'].includes(props.location.kind)) return "";
  return folderKey(props.location.sourceId, props.location.folder || "");
});
const isActive = (kind, value = "") => {
  if (props.location.kind !== kind) return false;
  if (kind === "collection") return props.location.collectionId === value;
  return true;
};
const MEMORY_REVIEW_URL = "http://127.0.0.1:8767/";
const openMemoryReview = () => globalThis.location.assign(MEMORY_REVIEW_URL);
</script>

<template>
  <aside class="folder-tree" :class="{ open: drawerOpen }" aria-label="素材位置">
    <div class="unified-tree-header">
      <button class="unified-brand" @click="standalone ? emit('open-assets') : emit('open-home')">
        <span class="brand-mark">木</span>
        <span><strong>木易素材库</strong><small>LOCAL LIBRARY</small></span>
      </button>
      <button class="tree-close-button" aria-label="关闭导航" @click="emit('close')">×</button>
      <nav class="unified-quick-nav" aria-label="主要功能">
        <button v-if="!standalone" :class="{ active: activeNavigation === 'home' }" @click="emit('open-home')"><span>⌂</span><b>首页</b></button>
        <p class="unified-quick-label">链接库</p>
        <button :class="{ active: activeNavigation === 'captures' }" @click="emit('open-captures')"><span>⌘</span><b>链接收集箱</b><small v-if="captureCount">{{ captureCount }}</small></button>
        <p class="unified-quick-label">本地素材</p>
        <button :class="{ active: activeNavigation === 'assets' }" @click="emit('open-assets')"><span>▦</span><b>全部素材</b></button>
        <button :class="{ active: activeNavigation === 'favorites' }" @click="emit('open-favorites')"><span>♥</span><b>我的收藏</b></button>
      </nav>
    </div>

    <div class="folder-tree-scroll">
      <section v-if="!standalone" class="tree-group content-creation-group">
        <p class="tree-group-title">内容创作</p>
        <button class="tree-flat-node" title="打开本机记忆中枢" @click="openMemoryReview"><span>忆</span><b>记忆回顾</b><small>本机</small></button>
      </section>

      <section class="tree-group">
        <p class="tree-group-title">{{ standalone ? "素材文件夹" : "本地视频文件夹" }}</p>
        <div v-for="source in sources" :key="source.id" class="tree-source">
          <div class="tree-node-row source-row-tree">
            <button
              class="tree-expander"
              :aria-expanded="expandedKeys.includes(folderKey(source.id, ''))"
              :aria-label="`${expandedKeys.includes(folderKey(source.id, '')) ? '收起' : '展开'} ${source.name}`"
              @click="emit('toggle', { sourceId: source.id, folder: '' })"
            >{{ expandedKeys.includes(folderKey(source.id, '')) ? '⌄' : '›' }}</button>
            <button
              class="tree-node-label"
              :class="{ active: selectedPhysicalKey === folderKey(source.id, '') }"
              :aria-current="selectedPhysicalKey === folderKey(source.id, '') ? 'page' : undefined"
              @click="emit('select', { kind: 'source', sourceId: source.id, folder: '' })"
            ><span class="tree-drive-icon">⌑</span><span class="tree-node-name">{{ source.name }}</span><i :class="source.status"></i></button>
          </div>
          <div v-if="expandedKeys.includes(folderKey(source.id, ''))" class="tree-source-children">
            <p v-if="loadingKeys.includes(folderKey(source.id, ''))" class="tree-node-state">正在读取…</p>
            <button v-else-if="errorByKey[folderKey(source.id, '')]" class="tree-node-state error" @click="emit('toggle', { sourceId: source.id, folder: '', retry: true })">读取失败，点此重试</button>
            <TreeFolderNode
              v-for="child in childrenByKey[folderKey(source.id, '')] || []"
              v-else
              :key="folderKey(child.source_id, child.path)"
              :node="child"
              :selected-key="selectedPhysicalKey"
              :expanded-keys="expandedKeys"
              :children-by-key="childrenByKey"
              :loading-keys="loadingKeys"
              :error-by-key="errorByKey"
              @select="emit('select', $event)"
              @toggle="emit('toggle', $event)"
            />
          </div>
        </div>
        <p v-if="!sources.length" class="tree-empty">还没有登记素材来源</p>
        <button class="tree-flat-node missing-index-node" :class="{ active: isActive('missing') }" @click="emit('select', { kind: 'missing' })"><span>⚠</span><b>失效索引</b><small>{{ missingCount }}</small></button>
      </section>

      <section class="tree-group collection-tree-group">
        <div class="tree-group-heading"><p class="tree-group-title">我的素材包</p><button title="新建素材包" @click="emit('create-collection')">＋</button></div>
        <button
          v-for="collection in collections"
          :key="collection.id"
          class="tree-flat-node"
          :class="{ active: isActive('collection', collection.id) }"
          @click="emit('select', { kind: 'collection', collectionId: collection.id })"
        ><span>▤</span><b>{{ collection.name }}</b><small>{{ collection.asset_count }}</small></button>
        <p v-if="!collections.length" class="tree-empty">把常用素材装进自己的素材包</p>
      </section>
    </div>

    <footer class="unified-tree-footer">
      <button :class="{ active: activeNavigation === 'settings' }" @click="emit('open-settings')"><span>⚙</span><b>来源与设置</b></button>
      <p><i></i>{{ standalone ? "只在本机运行" : "只在这台 Mac 上运行" }}</p>
    </footer>
  </aside>
</template>
