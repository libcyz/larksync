<script setup>
import { computed, onMounted, ref } from 'vue'
import { NLayout, NLayoutSider, NLayoutContent, NMenu, NButton, NEmpty, NText, NPopconfirm, useMessage } from 'naive-ui'
import { call } from '../api.js'
import SettingsModal from './SettingsModal.vue'
import AddTableModal from './AddTableModal.vue'
import Workspace from './Workspace.vue'

const message = useMessage()
const state = ref({ configured: false, user: null })
const tables = ref([])
const currentId = ref(null)
const showSettings = ref(false)
const showAdd = ref(false)

const current = computed(() => tables.value.find((t) => t.id === currentId.value))
const menu = computed(() => tables.value.map((t) => ({ key: t.id, label: t.name })))

async function load() {
  state.value = await call('state')
  tables.value = await call('tables')
  if (!currentId.value && tables.value.length) currentId.value = tables.value[0].id
  if (!state.value.configured || !state.value.user) showSettings.value = true
}

function onAdded(t) {
  tables.value.push(t)
  currentId.value = t.id
}

function onUpdated(t) {
  const i = tables.value.findIndex((x) => x.id === t.id)
  if (i >= 0) tables.value[i] = t
}

async function remove() {
  try {
    await call('remove_table', { id: currentId.value })
    tables.value = tables.value.filter((t) => t.id !== currentId.value)
    currentId.value = tables.value[0]?.id ?? null
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(() => load().catch((e) => message.error(e.message)))
</script>

<template>
  <n-layout has-sider position="absolute">
    <n-layout-sider bordered :width="220" content-style="display:flex;flex-direction:column;height:100%">
      <div class="brand">larksync</div>
      <n-menu :options="menu" :value="currentId" @update:value="(v) => (currentId = v)" class="menu" />
      <div class="sider-foot">
        <n-button block dashed @click="showAdd = true" :disabled="!state.user">+ 添加表格</n-button>
      </div>
    </n-layout-sider>

    <n-layout-content content-style="display:flex;flex-direction:column;height:100%">
      <header class="topbar">
        <div class="title" v-if="current">
          <strong>{{ current.name }}</strong>
          <n-text depth="3"> / {{ current.tab_title }}</n-text>
        </div>
        <div v-else />
        <div class="right">
          <n-popconfirm v-if="current" @positive-click="remove">
            <template #trigger><n-button quaternary size="small">移除</n-button></template>
            只移除本地的表格配置，不影响飞书上的表和写入记录。
          </n-popconfirm>
          <n-button quaternary size="small" @click="showSettings = true">
            {{ state.user ? state.user : '未登录' }} · 设置
          </n-button>
        </div>
      </header>

      <div class="body">
        <Workspace v-if="current" :key="current.id" :table="current" @updated="onUpdated" />
        <n-empty v-else class="empty" description="还没有表格">
          <template #extra>
            <n-button type="primary" @click="showAdd = true" :disabled="!state.user">添加表格</n-button>
          </template>
        </n-empty>
      </div>
    </n-layout-content>
  </n-layout>

  <SettingsModal v-model:show="showSettings" :state="state" @changed="(s) => (state = s)" />
  <AddTableModal v-model:show="showAdd" @added="onAdded" />
</template>

<style scoped>
.brand { font-weight: 600; font-size: 16px; padding: 16px 20px 8px; letter-spacing: .5px; }
.menu { flex: 1; overflow: auto; }
.sider-foot { padding: 12px; }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 10px 20px;
  border-bottom: 1px solid var(--n-border-color, rgba(128,128,128,.18)); min-height: 48px; }
.right { display: flex; gap: 4px; }
.body { flex: 1; overflow: auto; padding: 16px 20px; }
.empty { margin-top: 18vh; }
</style>
