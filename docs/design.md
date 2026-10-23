# larksync 设计文档

> 设计准则：**less is more**。每加一个功能、模块、依赖、配置项之前先问：不加行不行？

## 1. 要解决的问题

| 谁 | 现在 | 之后 |
|---|---|---|
| 非技术人员 | 对着 CSV 逐条核对在线表，手动改 | GUI 里选 CSV → 看差异 → 点确认 |
| 技术人员 | 手动下载表格，或每个项目各写一份拉取脚本 | `pip install larksync`，代码里 `Table(url).pull()` |

支持飞书**电子表格**和**多维表格**两种表。

## 2. 范围

**做：**

- 拉取：整张表 → `list[dict]` / CSV
- 初始化：用首个 CSV 生成空表的表头和数据（表头即字段定义）
- 更新：按主键匹配，只更新指定字段，写前预览差异、检测冲突
- 撤销：每次写入都可以一键还原

**不做（v1）：**

- CLI、TUI、Linux GUI
- 删除行（CSV 里缺的行只提示，不删）
- 多行表头、合并单元格、写公式
- 定时同步、实时同步
- 本地 schema 文件和表格别名配置（在线表的表头就是 schema，URL 就是标识）

## 3. 架构

```
larksync/
├── src/larksync/          核心库（纯 Python，三端 pip 安装）
│   ├── __init__.py        导出 Table、LarkError、configure
│   ├── table.py           Table：解析链接、分派后端、权限错误提示
│   ├── auth.py            应用配置；user / tenant 身份，token 缓存与续期
│   ├── http.py            请求、重试、限流、错误码 → 异常
│   ├── sheets.py          电子表格后端
│   ├── bitable.py         多维表格后端
│   ├── diff.py            差异计算（两种后端共用）
│   └── history.py         写入记录与撤销
├── gui/                   只打包 Win / Mac
│   ├── app.py             pywebview 入口，把核心库暴露给前端
│   └── frontend/          Vue 3 + Naive UI + vxe-table
└── docs/
```

**依赖：** `httpx`、`platformdirs`。不用 pydantic、PyYAML、pandas，有需要可以 `pd.DataFrame(t.pull())`。

GUI 只是核心库的一层壳，**所有逻辑都在核心库**。GUI 能做的事，代码里都能做。

## 4. 身份与凭证

### 4.1 身份

| 身份 | 能访问什么 | 适用场景 |
|---|---|---|
| **user（默认）** | 登录人能打开的所有表 | GUI、开发机、偶尔跑的 pipeline |
| tenant | 只有把应用加为协作者的表 | 长期无人值守的服务器 |

一个 `Table` 只用一种身份，由调用方显式指定。现有脚本里 tenant 失败后自动退回 user 的逻辑不保留：行为可以预测，比「自动」更重要。

### 4.2 应用

- **每人使用自己的飞书自建应用**，软件里不内置任何凭证。
- 权限范围：`wiki:wiki:readonly`、`sheets:spreadsheet`、`bitable:app`，以及获取 refresh_token 需要的 `offline_access`（以新版 OAuth 文档为准）。
- 重定向地址：`http://localhost:<port>/callback`。
- `docs/` 下提供一页「创建飞书应用」图文指引，内容包括：要勾选哪些权限、重定向地址填什么、如何发布。

### 4.3 文件位置

都放在 `platformdirs.user_config_dir("larksync")` 下：

```
config.json    {"app_id": "...", "app_secret": "...", "port": 8888}
               环境变量 LARKSYNC_APP_ID / LARKSYNC_APP_SECRET 优先
token.json     登录缓存，两种身份各一份（从现有 .feishu_token.json 的格式继承）
history/       写入记录（见 §7）
```

- **GUI 和核心库读写同一套文件。** 在 GUI 里配置过、登录过之后，同一台机器上的 Python 代码可以直接用，反过来也一样。
- **自动保存登录：** 首次登录后缓存 token，过期了用 refresh_token 静默续期，用户无感知；只有 refresh_token 也失效时才重新打开浏览器授权。
- **token 缓存绑定 app_id：** 换了应用，旧缓存自动作废，需要重新登录（沿用现有脚本的行为）。
- **服务器**：可以只设环境变量（tenant 身份），也可以把 `config.json` 和 `token.json` 一起拷过去（user 身份）。
- **服务器上用 user 身份**：在有浏览器的机器上登录一次，把 `token.json` 拷到服务器。refresh_token 大约 30 天有效，每次续期都会轮换。超过有效期没跑就要重新登录。
- 续期时**加文件锁**：多个进程同时续期，会让对方手里的 refresh_token 失效。

## 5. Python API

整个公开接口只有下面这些：

```python
import larksync
larksync.configure(app_id, app_secret)   # 每台机器一次（GUI 设置页调用的也是它）

from larksync import Table

t = Table(url)                       # 支持 wiki / sheets / base 链接，自动识别类型
t = Table(url, auth="tenant")
t = Table(url, tab="tblXXXXXXXX")   # 指定工作表 / 数据表，优先于链接里的参数

rows = t.pull()                      # list[dict[str, str]]，表头作为 key
t.pull("out.csv")                    # 传路径就写 CSV，返回同样的 rows

t.tabs()                             # [(id, 标题)]：同一个文档里的所有工作表 / 数据表
t.columns()                          # 表头（只读表头，不读数据）

t.init("first.csv")                  # 表必须为空：写入表头和数据

plan = t.diff("new.csv", key="Person_ID", columns=["状态", "时长"])
plan = t.diff(rows, key=["组别", "姓名"])   # 也可以传 list[dict]，可以用组合主键
print(plan)      # 补空 12 格 / 新增 3 行 / 不一致 2 格（未写入）/ 未匹配 5 行
plan.changed     # list[Change(key, column, old, new)]：在线为空、CSV 有值 → 写入
plan.conflicts   # 在线已有不同的值 → 只警告，不写
plan.added       # list[dict]：CSV 有、在线没有的行 → 写入（GUI 里默认不勾选）
plan.unmatched   # int：在线表有、CSV 里没有的行数（只提示）

plan.changed += plan.conflicts       # 人工确认后覆盖（也可以只挑其中几条）
record = plan.apply()                # 只写 changed 和 added，返回本次写入记录的 id

t.undo(record)                       # 撤销某次写入
```

参数说明：
- `columns=None` 表示 CSV 和在线表共有的列全部参与比较。
- CSV 里有、在线表里没有的列直接**报错**，不自动加列。

URL 中 sheet 的选择：链接里带 `?sheet=xxx` 或 `?table=xxx` 时用指定的那个，否则用第一个。

**迁移示例：** 项目里原有的拉表脚本用上这个库之后，拉取部分只剩下：

```python
for url in URLS:
    Table(url).pull(f"csv/{name} - 人员登记.csv")
```

## 6. 差异算法

两种后端共用这一套。后端只负责「读成行」和「把计划写回去」。

```
read() → 在线行 [(row_ref, {列: 值})]       row_ref：电子表格是行号，多维表格是 record_id
         本地行 [{列: 值}]

1. 校验：key 列在两边都存在；两边的 key 都不能重复（重复直接报错，并列出重复值）
2. 按 key 建索引
3. 本地有、在线没有 → added
   两边都有          → 逐列比较 columns：
                         本地为空              → 跳过（CSV 为空永远不会清空在线值）
                         在线为空、本地有值    → changed（补空，默认写入）
                         在线有值、和本地不同  → conflicts（只警告，人工确认后才写）
   在线有、本地没有  → unmatched
```

**默认只填空**：在线表上已经有的内容，不经人工确认绝不覆盖。

**值的比较：** 两边都先转成字符串，再去掉首尾空白后比较。CSV 本身就是文本，以文本为准最简单，也能保住手机号、编号的前导 0。

**冲突检测（apply 时）：** 写入前重新读取，确认 `changed` 里每个格子的当前值仍等于 `old`。如果有任何一格变了，就整体中止，并报告哪些格子被别人改过，让用户重新 diff。不做合并。

- 只改格子时，**只读涉及的那几行**（多维表格用 batch_get）：2.3 万条的表 apply 只要约 3 秒。
- 有新增行时要确认主键没被别人抢先加上，只能读全表。

## 7. 写入与撤销

1. 冲突检测通过后，先把本次计划（含所有 `old` 值）写到 `history/<时间戳>-<id>.json`，**然后再写飞书**。
2. 写入：
   - 电子表格：把相邻的修改合并成区域，批量写入；新增行追加到数据末尾。
   - 多维表格：按记录批量 update / create。
   - 两者都按接口上限分批（具体数值以官方文档为准）。
3. 中途失败：记录停在 `pending`，新增行的 ref 每批写完就落盘。撤销时逐格判断：当前值等于 new 的还原，等于 old 的说明没写成、跳过。
4. 撤销 = new → old，并删除本次新增的行，**同样经过冲突检测**，只读涉及的行。

撤销是唯一会删除行的地方，而且只删本工具自己新增的行。

## 8. 两种后端的差异

| | 电子表格 | 多维表格 |
|---|---|---|
| 表头 | 第 1 行 | 字段列表 |
| 行标识 | 行号（每次 apply 都重新读，不缓存） | record_id |
| 读值 | `FormattedValue`，即界面上看到的文本 | 按字段类型转成文本 |
| 写值 | 写文本。**待验证：** 写入的 `"007"` 能否保持为文本 | 文本 → 字段类型 |
| `init` | 写入表头和数据 | 按 CSV 表头建文本字段，再写入数据 |

多维表格 v1 支持写入的字段类型：文本、数字、单选、多选、日期、复选框。人员、附件、关联、公式、自动编号等类型**只读**；`columns` 里如果包含这些字段就报错。

## 9. GUI

定位是**一个小工具**，不是一个系统：单窗口，左边是已保存的表，右边是当前表的操作区。

### 9.1 使用流程

```
首次启动 ─→ 填 App ID / App Secret ─→ [飞书登录] 浏览器授权 ─→ 登录缓存在本机，以后打开免登录
                                                    │
添加表格 ─→ 粘贴链接 ─→ 自动列出工作表/数据表 ─→ 选一个 ─→ 读取表头 ─→ 保存为一个「表格配置」
                                                    │
更新     ─→ 拖入 CSV / xlsx ─→ 列对应：勾选要更新的列（可全选）、CSV 列 → 表格字段（同名自动对上）、勾选主键（可多选=联合主键）
                   ─→ 读全表、diff ─→ 预览（可逐条取消）─→ [写入飞书]
                                                    │
历史     ─→ 本表的写入记录 ─→ [撤销]
```

### 9.2 界面

```
┌──────────────┬──────────────────────────────────────────────┐
│ 表格          │ 登记表-阿芙 / 人员登记          张三 ▾  ⚙   │
│ ● 登记表-阿芙 │ ┌─────────────────────────────────────────┐ │
│   歌曲库      │ │   把 CSV 拖到这里                       │ │
│   测试表      │ └─────────────────────────────────────────┘ │
│              │ CSV 列          →  表格字段        主键      │
│              │ 人员ID          →  Person_ID        ◉        │
│              │ 审核状态        →  状态 ▾           ○        │
│              │ 备注            →  （不更新）▾      ○        │
│              │                                              │
│              │ 预览   新增 3 / 修改 12 / 未匹配 2           │
│              │ ☑ P001  状态  待定 → 通过                    │
│              │ ☑ P007  （新增）                             │
│ [+ 添加表格]  │                        [写入飞书]  [历史]   │
└──────────────┴──────────────────────────────────────────────┘
```

### 9.3 表格配置（每张表各存一份，互相隔离）

`<配置目录>/tables/<id>.json`：

```json
{"name": "登记表-阿芙", "url": "...", "tab": "2aBAcO", "tab_title": "人员登记",
 "key": ["Person_ID"], "mapping": {"人员ID": "Person_ID", "审核状态": "状态"}}
```

- 列对应和主键在第一次设置后会被记住，下次拖入同样格式的 CSV 直接就能预览。
- 历史页只显示本表的写入记录（按写入记录里的 `target` 过滤）。
- 删除表格配置不影响飞书上的表，也不删除写入记录。
- 列对应由 GUI 在内存里改 CSV 的列名，再把 `list[dict]` 交给 `Table.diff`，核心库不需要知道列对应这回事。

### 9.4 其他

- 表头默认只显示前 8 列，其余点「展开全部」查看。
- 文件支持 CSV（UTF-8 / GBK 自动识别）和 xlsx（读打开时显示的工作表）。桌面应用里选文件、拖入文件都由 Python 拿真实路径读取。
- 主键在一列不唯一时（如歌曲名重名），勾选多列组成联合主键（如 歌曲名 + 歌手名）；重复时报错会提示这么做。
- 读取大表要几十秒（见 §12），预览前显示进度：已读 N 条。
- 设置弹窗：App ID、App Secret、当前账号、退出登录。回调端口不在界面上显示，固定为 8888，应用后台的重定向地址按 `http://localhost:8888/callback` 配置。

**打包：** PyInstaller，用 GitHub Actions 的 `windows-latest` 和 `macos-latest` 构建。Mac 只出 arm64 包，除非有 Intel 机器需要支持。暂不签名，启动时检测 WebView2 是否已安装。

## 10. 错误处理

只定义**一个**异常类 `LarkError`，错误消息要写清楚出了什么问题、在哪张表哪一行、该怎么处理。例如：

```
没有权限读取「人员登记表」：当前是 tenant 身份，请把应用加为协作者，或改用 auth="user"
主键 Person_ID 在 CSV 中重复：P0012（第 5、19 行）
```

网络错误和限流（429 / 飞书频控错误码）在 `http.py` 里做指数退避重试，调用方看不到。

## 11. 开发顺序

每一步结束时都要有能用的东西：

1. ✅ **auth + http + sheets.pull**：从原有的拉表脚本迁移过来。
2. ✅ **diff + apply + history + bitable**：多维表格先做（record_id 稳定，写入和撤销更简单），已在 2.3 万条的测试表上实测。
3. ✅ **电子表格写入**：update / create / delete / add_fields，已在测试表上实测（init / add_fields 尚未实测）。
4. **GUI**：先在浏览器里用 mock 开发前端，再接 pywebview。
5. **打包与分发**：wheel 发到私有源或 git，GUI 安装包挂在 Release 上。

## 12. 待验证（动手前先用真实表测）

- [x] refresh_token：目前用的 v1 登录接口不需要 `offline_access` 就会返回 refresh_token，过期后静默续期已实测可用（2026-10-23）
- [x] 测试应用申请写权限 scope 后，用户授权能通过；多维表格写入、新增、删除均已实测（2026-10-23）
- [x] 多维表格文本字段写入 `"007"`、`"0123"` 能原样保留（2026-10-23）
- [x] 多维表格读取速度：服务端每页（500 条）约 0.9 秒，分页只能串行，2.3 万条需要约 45 秒。一般几百行的登记表只要 1～2 秒
- [x] 提速：diff 和 apply 不再读全表，只按文件里的主键值查询（search + filter，每次 OR 50 个值，并发 5 个）。2.3 万条的表：diff 2 行约 2 秒、120 行约 1.8 秒，新增 1 行 apply 约 4 秒。主键不是文本类型、或文件超过 2000 行时，仍然读全表（2026-10-23）
- [x] Linux 开发环境：pywebview 在 GTK 上取不到拖入文件的路径（用 get_text 读 URI 列表），gui/app.py 里改用 get_uris 自己取。Windows / Mac 走 pywebview 自带的实现
- [x] 电子表格写入 `"007"`、`"0123"`、`"2026-01-02"` 原样保留为文本，不会被转成数字或日期（2026-10-23）
- [x] 电子表格增删行列（dimension_range）的 startIndex / endIndex 从 1 开始、两端都包含（2026-10-23）
- [x] 权限：user 身份需要 `wiki:wiki:readonly`、`sheets:spreadsheet`、`bitable:app`。后台改完权限并发布后，可能要过几分钟才生效（2026-10-23）
- [ ] 电子表格和多维表格单次写入的行数上限、频控阈值
- [ ] 普通员工能否自行创建并发布带 `sheets:spreadsheet`、`bitable:app` 写权限的自建应用，还是每个应用都要管理员审核
