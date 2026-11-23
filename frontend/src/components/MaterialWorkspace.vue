<script setup>
import FolderTree from "./FolderTree.vue";

defineProps({
  standalone: Boolean,
  view: { type: String, default: "assets" },
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
  "close-drawer",
  "open-drawer",
  "open-home",
  "open-assets",
  "open-favorites",
  "open-captures",
  "open-settings",
]);
</script>

<template>
  <div class="material-workspace">
    <FolderTree
      :standalone="standalone"
      :active-navigation="activeNavigation"
      :sources="sources"
      :collections="collections"
      :location="location"
      :capture-count="captureCount"
      :missing-count="missingCount"
      :expanded-keys="expandedKeys"
      :children-by-key="childrenByKey"
      :loading-keys="loadingKeys"
      :error-by-key="errorByKey"
      :drawer-open="drawerOpen"
      @select="emit('select', $event)"
      @toggle="emit('toggle', $event)"
      @create-collection="emit('create-collection')"
      @close="emit('close-drawer')"
      @open-home="emit('open-home')"
      @open-assets="emit('open-assets')"
      @open-favorites="emit('open-favorites')"
      @open-captures="emit('open-captures')"
      @open-settings="emit('open-settings')"
    />
    <button v-if="drawerOpen" class="tree-drawer-backdrop" aria-label="关闭文件夹" @click="emit('close-drawer')"></button>
    <section class="workspace-content" :class="{ 'page-content': view !== 'assets' }">
      <button class="unified-mobile-trigger" aria-label="打开导航" @click="emit('open-drawer')">☰ 导航</button>
      <slot></slot>
    </section>
  </div>
</template>
