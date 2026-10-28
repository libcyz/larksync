<script setup>
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { NCard, NButton, NSelect, NCheckbox, NDataTable, NTabs, NTabPane, NTag, NAlert, NSpace, NText, useMessage, useDialog } from 'naive-ui'
import { call, fileToBase64, native, progress } from '../api.js'
import ColumnTags from './ColumnTags.vue'
import HistoryDrawer from './HistoryDrawer.vue'

const props = defineProps({ table: Object })
const emit = defineEmits(['updated'])
const message = useMessage()
const dialog = useDialog()

const csv = ref(null)          // { name, header, count }
const cols = ref([])           // 每个 CSV 列一行：{ col, field, use, key }
const plan = ref(null)         // { changed, conflicts, added, unmatched }
const sel = ref({ changed: [], conflicts: [], added: [] })
const loading = ref('')        // 'cols' | 'file' | 'diff' | 'apply'
const dragging = ref(false)
const showHistory = ref(false)
const fileInput = ref(null)

// ---- 表头 ----

async function refreshColumns() {
  loading.value = 'cols'
  try {
    emit('updated', await call('refresh_columns', { id: props.table.id }))
    message.success('表头已刷新')
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = ''
  }
}

// ---- 1. 文件 ----

async function load(task) {
  loading.value = 'file'
  try {
    const res = await task()
    if (res?.header) onLoaded(res)
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = ''
  }
}

function onLoaded(res) {
  csv.value = res
  const saved = props.table.mapping || {}
  const savedKeys = props.table.key || []
  const hasSaved = Object.keys(saved).length > 0
  const fields = props.table.columns
  cols.value = res.header.map((col) => {
    const field = fields.includes(saved[col]) ? saved[col] : fields.includes(col) ? col : ''
    const key = !!field && savedKeys.includes(field)
    return { col, field, key, use: !!field && !key && (!hasSaved || col in saved) }
  })
  plan.value = null
}

function pick() {
  if (native) load(() => call('pick_file', { table_id: props.table.id }))
  else fileInput.value.click()
}

function onInput(e) {
  const file = e.target.files[0]
  e.target.value = ''
  if (file) load(async () => call('read_csv', { table_id: props.table.id, name: file.name, data: await fileToBase64(file) }))
}

function onDrop(e) {
  dragging.value = false
  const file = e.dataTransfer.files[0]
  if (native) window.pywebview?.api.log(`drop 事件：${file ? file.name + ' ' + file.size + 'B' : '没有文件'}`)
  // 两条路一起走：这里直接读文件内容；桌面应用里 Python 拿到路径后也会回调 window.larksyncDrop
  if (file) load(async () => call('read_csv', { table_id: props.table.id, name: file.name, data: await fileToBase64(file) }))
}

onMounted(() => {
  window.larksyncDrop = (path) => load(() => call('read_path', { table_id: props.table.id, path }))
})
onUnmounted(() => { delete window.larksyncDrop })

// ---- 2. 列对应 ----

const keys = computed(() => cols.value.filter((r) => r.key && r.field).map((r) => r.field))
const updating = computed(() => cols.value.filter((r) => r.use && r.field && !r.key).map((r) => r.field))
const eligible = computed(() => cols.value.filter((r) => r.field && !r.key))
const dupes = computed(() => {
  const used = cols.value.filter((r) => r.field && (r.use || r.key)).map((r) => r.field)
  return [...new Set(used.filter((v, i) => used.indexOf(v) !== i))]
})
// 只勾主键、不勾「更新」也可以：这时只找新增的行
const canDiff = computed(() => csv.value && keys.value.length && !dupes.value.length)

watch(cols, () => { plan.value = null }, { deep: true })

const fieldOptions = computed(() => props.table.columns.map((c) => ({ label: c, value: c })))

const mapColumns = computed(() => [
  {
    key: 'use', width: 72, align: 'center',
    title: () => h(NCheckbox, {
      checked: eligible.value.length > 0 && eligible.value.every((r) => r.use),
      indeterminate: eligible.value.some((r) => r.use) && !eligible.value.every((r) => r.use),
      disabled: !eligible.value.length,
      onUpdateChecked: (v) => eligible.value.forEach((r) => { r.use = v }),
    }, () => '更新'),
    render: (r) => h(NCheckbox, { checked: r.use, disabled: !r.field || r.key, onUpdateChecked: (v) => { r.use = v } }),
  },
  { title: 'CSV 列', key: 'col', ellipsis: { tooltip: true } },
  {
    title: '→ 表格字段', key: 'field',
    render: (r) => h(NSelect, {
      size: 'small', options: fieldOptions.value, value: r.field || null, clearable: true, filterable: true,
      placeholder: '不对应', status: dupes.value.includes(r.field) && (r.use || r.key) ? 'error' : undefined,
      'onUpdate:value': (v) => {
        r.field = v || ''
        if (!v) { r.use = false; r.key = false } else if (!r.key) r.use = true
      },
    }),
  },
  {
    title: '主键', key: 'key', width: 64, align: 'center',
    render: (r) => h(NCheckbox, {
      checked: r.key, disabled: !r.field,
      onUpdateChecked: (v) => { r.key = v; r.use = !v },
    }),
  },
])

// ---- 3. 预览 ----

async function runDiff() {
  loading.value = 'diff'
  const mapping = Object.fromEntries(cols.value.filter((r) => r.field && (r.use || r.key)).map((r) => [r.col, r.field]))
  try {
    plan.value = await call('diff', { table_id: props.table.id, mapping, key: keys.value })
    sel.value = { changed: plan.value.changed.map((c) => c.i), conflicts: [], added: [] }
    emit('updated', { ...props.table, mapping, key: [...keys.value] })
  } catch (e) {
    message.error(e.message, { duration: 10000, closable: true })
  } finally {
    loading.value = ''
  }
}

const cellCols = (withOld) => [
  { type: 'selection' },
  { title: '主键', key: 'key', width: 180, ellipsis: { tooltip: true } },
  { title: '字段', key: 'column', width: 140, ellipsis: { tooltip: true } },
  ...(withOld ? [{ title: '在线值', key: 'old', ellipsis: { tooltip: true },
    render: (r) => h(NText, { depth: 3, delete: sel.value.conflicts.includes(r.i) }, () => r.old) }] : []),
  { title: withOld ? 'CSV 值' : '写入', key: 'new', ellipsis: { tooltip: true },
    render: (r) => h(NText, { type: withOld ? 'warning' : 'success' }, () => r.new) },
]
const addedCols = [
  { type: 'selection' },
  { title: '主键', key: 'key', width: 180, ellipsis: { tooltip: true } },
  { title: '内容', key: 'values', ellipsis: { tooltip: true },
    render: (r) => Object.entries(r.values).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join('，') },
]

const total = computed(() => sel.value.changed.length + sel.value.conflicts.length + sel.value.added.length)

function confirmApply() {
  const { changed, conflicts, added } = sel.value
  const parts = [changed.length && `补空 ${changed.length} 格`, conflicts.length && `覆盖 ${conflicts.length} 格`,
    added.length && `新增 ${added.length} 行`].filter(Boolean)
  dialog.warning({
    title: '写入飞书',
    content: `将${parts.join('、')}。写入后可以在「历史」里撤销。`,
    positiveText: '写入',
    negativeText: '取消',
    onPositiveClick: apply,
  })
}

async function apply() {
  loading.value = 'apply'
  progress.value = null
  try {
    await call('apply', sel.value)
    message.success('已写入飞书，可在「历史」里撤销')
    plan.value = null
  } catch (e) {
    message.error(e.message, { duration: 10000, closable: true })
  } finally {
    loading.value = ''
  }
}
</script>

<template>
  <n-space vertical :size="16">
    <n-card size="small" :title="`表头（${table.columns.length} 列）`">
      <template #header-extra>
        <n-button size="small" quaternary :loading="loading === 'cols'" @click="refreshColumns">刷新</n-button>
        <n-button size="small" quaternary @click="showHistory = true">历史</n-button>
      </template>
      <ColumnTags :columns="table.columns" :keys="table.key || []" />
    </n-card>

    <n-card size="small" title="1  选择文件">
      <div class="drop" :class="{ on: dragging }" @click="pick"
        @dragover.prevent="dragging = true" @dragleave="dragging = false" @drop.prevent="onDrop">
        <n-text v-if="loading === 'file'" depth="3">读取中…</n-text>
        <template v-else-if="csv">
          <strong>{{ csv.name }}</strong>
          <n-text depth="3">　{{ csv.count }} 行 · {{ csv.header.length }} 列　（点击或拖入以更换）</n-text>
        </template>
        <n-text v-else depth="3">把 CSV / xlsx 拖到这里，或点击选择文件</n-text>
      </div>
      <input ref="fileInput" type="file" accept=".csv,.xlsx" hidden @change="onInput" />
    </n-card>

    <n-card v-if="csv" size="small" title="2  列对应">
      <template #header-extra>
        <n-text depth="3" style="font-size: 12px">默认只填在线表的空格子；已有不同值的只提示，不覆盖</n-text>
      </template>
      <n-data-table size="small" :columns="mapColumns" :data="cols" :row-key="(r) => r.col"
        :max-height="300" :bordered="false" />
      <n-space justify="space-between" align="center" style="margin-top: 12px">
        <n-text :type="dupes.length ? 'error' : 'default'" depth="3">
          <template v-if="dupes.length">多个 CSV 列对应到了同一个字段：{{ dupes.join('、') }}</template>
          <template v-else-if="!keys.length">请勾选主键（用来匹配在线表里的行，一列不唯一时可以多勾几列）</template>
          <template v-else-if="!updating.length">按「{{ keys.join(' + ') }}」匹配，只找新增的行（新行只写主键）</template>
          <template v-else>按「{{ keys.join(' + ') }}」匹配，更新 {{ updating.length }} 个字段</template>
        </n-text>
        <n-button type="primary" :disabled="!canDiff" :loading="loading === 'diff'" @click="runDiff">
          {{ loading === 'diff' ? '正在读取在线表…' : '生成预览' }}
        </n-button>
      </n-space>
    </n-card>

    <n-card v-if="plan" size="small" title="3  预览">
      <template #header-extra>
        <n-space :size="6">
          <n-tag size="small" type="success" round>补空 {{ plan.changed.length }}</n-tag>
          <n-tag size="small" type="warning" round>不一致 {{ plan.conflicts.length }}</n-tag>
          <n-tag size="small" type="info" round>新增 {{ plan.added.length }}</n-tag>
          <n-tag size="small" round>未匹配 {{ plan.unmatched }}</n-tag>
        </n-space>
      </template>
      <n-tabs type="line" size="small" animated>
        <n-tab-pane name="changed" :tab="`补空 ${plan.changed.length}`">
          <n-data-table size="small" virtual-scroll :max-height="320" :row-key="(r) => r.i"
            :columns="cellCols(false)" :data="plan.changed"
            v-model:checked-row-keys="sel.changed" />
        </n-tab-pane>
        <n-tab-pane name="conflicts" :tab="`不一致 ${plan.conflicts.length}`">
          <n-alert v-if="plan.conflicts.length" type="warning" :show-icon="false" style="margin-bottom: 8px">
            这些格子在线已有不同的值，默认不写入。请人工核对，确认要用文件里的值覆盖的再勾选。
          </n-alert>
          <n-data-table size="small" virtual-scroll :max-height="320" :row-key="(r) => r.i"
            :columns="cellCols(true)" :data="plan.conflicts"
            v-model:checked-row-keys="sel.conflicts" />
        </n-tab-pane>
        <n-tab-pane name="added" :tab="`新增 ${plan.added.length}`">
          <n-alert v-if="plan.added.length" type="info" :show-icon="false" style="margin-bottom: 8px">
            这些行在线表里没有（按主键找不到），默认不新增。确认要加到表里的再勾选。
          </n-alert>
          <n-data-table size="small" virtual-scroll :max-height="320" :row-key="(r) => r.i"
            :columns="addedCols" :data="plan.added"
            v-model:checked-row-keys="sel.added" />
        </n-tab-pane>
        <n-tab-pane name="unmatched" :tab="`未匹配 ${plan.unmatched}`">
          <n-text depth="3">在线表里有、文件里没有的 {{ plan.unmatched }} 行，不会做任何改动。</n-text>
        </n-tab-pane>
      </n-tabs>
      <n-space justify="end" style="margin-top: 12px">
        <n-button type="primary" :disabled="!total" :loading="loading === 'apply'" @click="confirmApply">
          <template v-if="loading === 'apply' && progress">{{ progress.stage }}中 {{ progress.done }} / {{ progress.total }}</template>
          <template v-else>写入飞书（{{ total }}）</template>
        </n-button>
      </n-space>
    </n-card>
  </n-space>

  <HistoryDrawer v-model:show="showHistory" :table="table" />
</template>

<style scoped>
.drop { border: 1.5px dashed rgba(128, 128, 128, .35); border-radius: 8px; padding: 28px 16px;
  text-align: center; cursor: pointer; transition: border-color .15s, background .15s; }
.drop:hover, .drop.on { border-color: #3370ff; background: rgba(51, 112, 255, .06); }
</style>
