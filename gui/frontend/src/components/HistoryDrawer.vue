<script setup>
import { ref, watch } from 'vue'
import { NDrawer, NDrawerContent, NList, NListItem, NTag, NButton, NPopconfirm, NEmpty, NSpace, NText, useMessage } from 'naive-ui'
import { call, progress } from '../api.js'

const props = defineProps({ show: Boolean, table: Object })
const emit = defineEmits(['update:show'])
const message = useMessage()
const items = ref([])
const busy = ref(null)

const STATUS = { done: ['已写入', 'success'], undone: ['已撤销', 'default'], pending: ['未完成', 'error'] }

async function load() {
  try {
    items.value = await call('history', { table_id: props.table.id })
  } catch (e) {
    message.error(e.message)
  }
}

async function undo(id) {
  busy.value = id
  progress.value = null
  try {
    await call('undo', { table_id: props.table.id, record_id: id })
    message.success('已撤销')
    await load()
  } catch (e) {
    message.error(e.message, { duration: 8000 })
  } finally {
    busy.value = null
  }
}

watch(() => props.show, (v) => v && load())
</script>

<template>
  <n-drawer :show="show" @update:show="(v) => emit('update:show', v)" :width="420">
    <n-drawer-content :title="`历史 · ${table.name}`" closable>
      <n-empty v-if="!items.length" description="还没有写入记录" style="margin-top: 80px" />
      <n-list v-else>
        <n-list-item v-for="r in items" :key="r.id">
          <n-space vertical :size="4">
            <n-space align="center" :size="8">
              <n-text>{{ r.time }}</n-text>
              <n-tag size="small" :type="STATUS[r.status][1]">{{ STATUS[r.status][0] }}</n-tag>
            </n-space>
            <n-text depth="3" style="font-size: 12px">
              补空 {{ r.fills }} 格 · 覆盖 {{ r.overwrites }} 格 · 新增 {{ r.added }} 行
            </n-text>
          </n-space>
          <template #suffix>
            <n-popconfirm v-if="r.status !== 'undone'" @positive-click="undo(r.id)">
              <template #trigger>
                <n-button size="small" :loading="busy === r.id">
                  {{ busy === r.id && progress ? `${progress.stage}中 ${progress.done} / ${progress.total}` : '撤销' }}
                </n-button>
              </template>
              还原这次改过的格子、删除这次新增的行。之后又被别人改过的话会中止。
            </n-popconfirm>
          </template>
        </n-list-item>
      </n-list>
    </n-drawer-content>
  </n-drawer>
</template>
