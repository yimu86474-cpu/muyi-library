<script setup>
import { computed } from "vue";
import { folderKey } from "../utils.js";

defineOptions({ name: "TreeFolderNode" });

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  selectedKey: { type: String, default: "" },
  expandedKeys: { type: Array, default: () => [] },
  childrenByKey: { type: Object, default: () => ({}) },
  loadingKeys: { type: Array, default: () => [] },
  errorByKey: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["select", "toggle"]);

const key = computed(() => folderKey(props.node.source_id, props.node.path));
const expanded = computed(() => props.expandedKeys.includes(key.value));
const children = computed(() => props.childrenByKey[key.value] || []);
const loading = computed(() => props.loadingKeys.includes(key.value));
const error = computed(() => props.errorByKey[key.value] || "");
</script>

<template>
  <div class="tree-folder-node">
    <div class="tree-node-row" :style="{ '--tree-depth': depth }">
      <button
        v-if="node.has_children"
        class="tree-expander"
        :aria-expanded="expanded"
        :aria-label="`${expanded ? '收起' : '展开'} ${node.name}`"
        @click="emit('toggle', { sourceId: node.source_id, folder: node.path })"
      >{{ expanded ? '⌄' : '›' }}</button>
      <span v-else class="tree-expander-placeholder"></span>
      <button
        class="tree-node-label"
        :class="{ active: selectedKey === key }"
        :aria-current="selectedKey === key ? 'page' : undefined"
        @click="emit('select', { kind: 'folder', sourceId: node.source_id, folder: node.path })"
      >
        <span class="tree-folder-icon">▰</span>
        <span class="tree-node-name">{{ node.name }}</span>
        <small>{{ node.asset_count }}</small>
      </button>
    </div>
    <div v-if="expanded" class="tree-node-children">
      <p v-if="loading" class="tree-node-state">正在读取…</p>
      <button v-else-if="error" class="tree-node-state error" @click="emit('toggle', { sourceId: node.source_id, folder: node.path, retry: true })">读取失败，点此重试</button>
      <TreeFolderNode
        v-for="child in children"
        v-else
        :key="folderKey(child.source_id, child.path)"
        :node="child"
        :depth="depth + 1"
        :selected-key="selectedKey"
        :expanded-keys="expandedKeys"
        :children-by-key="childrenByKey"
        :loading-keys="loadingKeys"
        :error-by-key="errorByKey"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
      />
    </div>
  </div>
</template>
