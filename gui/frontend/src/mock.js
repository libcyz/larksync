// 浏览器开发用的假后端：接口和 gui/app.py 的 Api 一一对应
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
// 模拟 Python 推送进度
async function fakeProgress(stage, total) {
  window.larksyncProgress?.({ stage: '检查', done: 0, total })
  await sleep(500)
  for (let done = 1; done <= total; done++) {
    window.larksyncProgress?.({ stage, done, total })
    await sleep(300)
  }
}
const copy = (x) => JSON.parse(JSON.stringify(x))   // 和真实后端一样返回副本，界面改了不影响这里

const db = {
  cfg: { app_id: '', app_secret: '', port: 8888 },
  user: null,
  tables: [
    { id: 't1', name: '示例-订单', url: 'https://example.feishu.cn/sheets/shtDemo', tab: 'sht1', tab_title: 'Sheet1',
      target: 'sheet:shtDemo:sht1', columns: ['订单号', '客户', '评分', '备注', '链接'], key: [], mapping: {} },
    { id: 't2', name: '歌曲库', url: 'https://example.feishu.cn/base/basDemo', tab: 'tbl1', tab_title: '主表',
      target: 'bitable:basDemo:tbl1', columns: ['歌曲名', '歌手名', '歌曲唯一ID', '来源'], key: [], mapping: {} },
  ],
  rows: {
    t1: [
      { 订单号: '816', 客户: '张三', 评分: '4', 备注: '无', 链接: '' },
      { 订单号: '817', 客户: '李四', 评分: '4', 备注: '', 链接: '' },
      { 订单号: '818', 客户: '王五', 评分: '', 备注: '', 链接: '' },
      { 订单号: '819', 客户: '赵六', 评分: '3', 备注: '', 链接: '' },
      { 订单号: '820', 客户: '钱七', 评分: '4', 备注: '地址不全', 链接: '' },
    ],
    t2: [],
  },
  csv: {},
  plan: null,
  history: [],
}

function parseCsv(text) {
  const lines = text.replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim())
  const header = lines[0].split(',').map((s) => s.trim())
  const rows = lines.slice(1).map((l) => {
    const v = l.split(',')
    return Object.fromEntries(header.map((h, i) => [h, (v[i] || '').trim()]))
  })
  return { header, rows }
}

export const mock = {
  async state() {
    return { configured: !!(db.cfg.app_id && db.cfg.app_secret), app_id: db.cfg.app_id, port: db.cfg.port, user: db.user }
  },
  async save_settings({ app_id, app_secret, port }) {
    db.cfg = { app_id, app_secret: app_secret || db.cfg.app_secret, port }
    return mock.state()
  },
  async login() {
    await sleep(1200)
    db.user = 'lark'
    return mock.state()
  },
  async logout() {
    db.user = null
    return mock.state()
  },
  async tables() {
    return copy(db.tables)
  },
  async probe({ url }) {
    await sleep(600)
    if (!/feishu\.cn\/(wiki|sheets|base)\//.test(url)) return { error: `认不出的飞书链接：${url}` }
    return { title: '示例文档', tabs: [{ id: 'sht1', title: 'Sheet1' }, { id: 'sht2', title: '人员登记' }], selected: 'sht1' }
  },
  async columns({ url, tab }) {
    await sleep(300)
    return tab === 'sht1' ? ['Person_ID', '姓名', '状态', '备注'] : ['组别', 'Group_ID', 'Person_ID_1', 'Person_ID_2', '城市']
  },
  async add_table({ url, tab, name }) {
    await sleep(500)
    const tab_title = tab === 'sht1' ? 'Sheet1' : '人员登记'
    const t = { id: 't' + Date.now(), name, url, tab, tab_title, target: `sheet:x:${tab}`,
      columns: await mock.columns({ url, tab }), key: [], mapping: {} }
    db.tables.push(t)
    db.rows[t.id] = []
    return copy(t)
  },
  async remove_table({ id }) {
    db.tables = db.tables.filter((t) => t.id !== id)
    return {}
  },
  async refresh_columns({ id }) {
    return copy(db.tables.find((t) => t.id === id))
  },
  async read_csv({ table_id, name, data }) {
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0))
    const { header, rows } = parseCsv(new TextDecoder().decode(bytes))
    db.csv[table_id] = { header, rows }
    return { name, header, count: rows.length }
  },
  async diff({ table_id, mapping, key }) {
    await sleep(900)
    const t = db.tables.find((x) => x.id === table_id)
    const fields = Object.values(mapping).filter(Boolean)
    if (!key.length || key.some((k) => !fields.includes(k))) return { error: '请勾选主键，主键必须是已对应的字段' }
    t.mapping = copy(mapping)
    t.key = [...key]
    const kf = (r) => key.map((k) => r[k] || '').join('/')
    const online = Object.fromEntries(db.rows[table_id].map((r) => [kf(r), r]))
    const changed = [], conflicts = [], added = []
    let seen = 0
    for (const raw of db.csv[table_id].rows) {
      const r = Object.fromEntries(Object.entries(mapping).filter(([, f]) => f).map(([c, f]) => [f, raw[c] || '']))
      const o = online[kf(r)]
      if (!o) { added.push({ i: added.length, key: kf(r), values: r }); continue }
      seen++
      for (const f of fields) {
        if (key.includes(f) || !r[f] || r[f] === (o[f] || '')) continue
        const list = o[f] ? conflicts : changed
        list.push({ i: list.length, key: kf(r), column: f, old: o[f] || '', new: r[f] })
      }
    }
    db.plan = { table_id, key, changed, conflicts, added }
    return { changed, conflicts, added, unmatched: db.rows[table_id].length - seen }
  },
  async apply({ changed, conflicts, added }) {
    await fakeProgress('写入', changed.length + conflicts.length + added.length)
    const p = db.plan
    const cells = [...changed.map((i) => p.changed[i]), ...conflicts.map((i) => p.conflicts[i])]
    const rows = db.rows[p.table_id]
    const kf = (r) => p.key.map((k) => r[k] || '').join('/')
    for (const c of cells) rows.find((r) => kf(r) === c.key)[c.column] = c.new
    const newRows = added.map((i) => p.added[i].values)
    rows.push(...newRows)
    const id = new Date().toISOString().replace(/\D/g, '').slice(0, 14)
    db.history.unshift({ id, table_id: p.table_id, time: new Date().toLocaleString('zh-CN'), status: 'done',
      fills: cells.filter((c) => !c.old).length, overwrites: cells.filter((c) => c.old).length, added: newRows.length, cells, newRows })
    db.plan = null
    return { record_id: id }
  },
  async history({ table_id }) {
    return copy(db.history.filter((h) => h.table_id === table_id))
  },
  async undo({ record_id }) {
    await fakeProgress('撤销', 3)
    const h = db.history.find((x) => x.id === record_id)
    const t = db.tables.find((x) => x.id === h.table_id)
    const rows = db.rows[h.table_id]
    const kf = (r) => t.key.map((k) => r[k] || '').join('/')
    for (const c of h.cells) rows.find((r) => kf(r) === c.key)[c.column] = c.old
    db.rows[h.table_id] = rows.filter((r) => !h.newRows.includes(r))
    h.status = 'undone'
    return {}
  },
}
