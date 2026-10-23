<script setup>
import { computed, ref } from 'vue'
import { NTag, NButton, NText } from 'naive-ui'

// 表头标签：默认只显示前 8 列，其余点开再看
const props = defineProps({ columns: Array, keys: { type: Array, default: () => [] } })
const LIMIT = 8
const open = ref(false)
const shown = computed(() => (open.value ? props.columns : props.columns.slice(0, LIMIT)))
</script>

<template>
  <div class="cols">
    <n-text v-if="!columns.length" depth="3">这个工作表还没有表头</n-text>
    <n-tag v-for="c in shown" :key="c" size="small" :bordered="false"
      :type="keys.includes(c) ? 'primary' : 'default'">{{ c }}</n-tag>
    <n-button v-if="columns.length > LIMIT" text size="small" type="primary" @click="open = !open">
      {{ open ? '收起' : `展开全部 ${columns.length} 列` }}
    </n-button>
  </div>
</template>

<style scoped>
.cols { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; max-height: 180px; overflow: auto; }
</style>
