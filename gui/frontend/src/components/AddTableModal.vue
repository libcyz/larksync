<script setup>
import { computed, ref, watch } from 'vue'
import { NModal, NForm, NFormItem, NInput, NButton, NSelect, NSpace, NSpin, useMessage } from 'naive-ui'
import { call } from '../api.js'
import ColumnTags from './ColumnTags.vue'

const props = defineProps({ show: Boolean })
const emit = defineEmits(['update:show', 'added'])
const message = useMessage()

const url = ref('')
const tabs = ref([])
const tab = ref(null)
const name = ref('')
const columns = ref(null)   // 选中工作表的表头；null 表示还没读到
const loadingCols = ref(false)
const busy = ref(false)

const tabOptions = computed(() => tabs.value.map((t) => ({ label: `${t.title}（${t.id}）`, value: t.id })))

watch(() => props.show, (v) => {
  if (v) { url.value = ''; tabs.value = []; tab.value = null; name.value = ''; columns.value = null }
})

watch(tab, async (id) => {
  columns.value = null
  if (!id) return
  loadingCols.value = true
  try {
    const cols = await call('columns', { url: url.value.trim(), tab: id })
    if (tab.value === id) columns.value = cols   // 期间又切了工作表就丢弃
  } catch (e) {
    message.error(e.message)
  } finally {
    loadingCols.value = false
  }
})

async function probe() {
  busy.value = true
  try {
    const r = await call('probe', { url: url.value.trim() })
    tabs.value = r.tabs
    tab.value = r.selected
    if (!name.value) name.value = r.title   // 默认用文档标题，工作表名会显示在顶栏
  } catch (e) {
    message.error(e.message)
  } finally {
    busy.value = false
  }
}

async function save() {
  busy.value = true
  try {
    const t = await call('add_table', { url: url.value.trim(), tab: tab.value, name: name.value.trim() })
    emit('added', t)
    emit('update:show', false)
  } catch (e) {
    message.error(e.message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <n-modal :show="show" @update:show="(v) => emit('update:show', v)" preset="card" title="添加表格" style="width: 520px">
    <n-form label-placement="left" label-width="72">
      <n-form-item label="链接">
        <n-input v-model:value="url" placeholder="粘贴飞书电子表格 / 多维表格 / 知识库链接" @keyup.enter="probe" />
        <n-button style="margin-left: 8px" :loading="busy && !tabs.length" :disabled="!url.trim()" @click="probe">读取</n-button>
      </n-form-item>
      <template v-if="tabs.length">
        <n-form-item label="工作表">
          <n-select v-model:value="tab" :options="tabOptions" />
        </n-form-item>
        <n-form-item label="表头">
          <n-spin v-if="loadingCols" size="small" />
          <ColumnTags v-else-if="columns" :columns="columns" />
        </n-form-item>
        <n-form-item label="名称">
          <n-input v-model:value="name" placeholder="在左侧列表里显示的名字" />
        </n-form-item>
      </template>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="emit('update:show', false)">取消</n-button>
        <n-button type="primary" :disabled="!tab || !name.trim() || !columns" :loading="busy && !!tabs.length" @click="save">保存</n-button>
      </n-space>
    </template>
  </n-modal>
</template>
