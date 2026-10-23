# Python 调用

本文说明技术人员在 Python 代码中调用 larksync 的方法。术语和更新规则见 [README](../README.md)。

## 安装

larksync 需要 Python 3.10 或更高版本。

larksync 还没有发布到 PyPI。使用以下方法之一安装：

```bash
# 本机，larksync 源码在相邻目录
uv add --editable ../larksync

# 源码推送到 git 仓库后
uv add "larksync @ git+https://<仓库地址>/larksync.git"
pip install "git+https://<仓库地址>/larksync.git"
```

默认安装不包含 GUI 依赖。

## 配置凭证

有浏览器的机器上，运行一次：

```python
import larksync
larksync.configure("cli_xxx", "app_secret")
```

服务器上，设置环境变量。环境变量优先于 `configure()` 的配置。

```bash
export LARKSYNC_APP_ID=cli_xxx
export LARKSYNC_APP_SECRET=xxx
```

## 选择身份

| 身份 | 写法 | 可以访问的在线表 | 适用场景 |
|---|---|---|---|
| user | `Table(url)` | 登录人可以打开的在线表 | 开发机、偶尔运行的 pipeline |
| tenant | `Table(url, auth="tenant")` | 应用是协作者的在线表 | 无人值守的服务器 |

user 身份首次使用时打开浏览器授权。之后 larksync 自动续期。

服务器上使用 user 身份时，在有浏览器的机器上登录一次。然后把 `config.json` 和 `token.json` 复制到服务器的配置目录。长时间不运行时，登录会过期，必须重新登录。

tenant 身份必须把应用加为每张在线表的协作者。

## 拉取在线表

```python
from larksync import Table

t = Table("https://xxx.feishu.cn/wiki/<token>?sheet=<id>")
rows = t.pull()            # list[dict]，表头作为 key
t.pull("out.csv")          # 同时写入 CSV 文件
```

- 链接带 `?sheet=` 或 `?table=` 时，larksync 打开指定的在线表。
- 链接不带参数时，larksync 打开文档中的第一张在线表。
- `Table(url, tab="<id>")` 指定在线表，优先于链接中的参数。
- 输出的 CSV 用 `utf-8-sig` 编码。Excel 可以直接打开。
- 表头为空的列和整行为空的行不输出。

## 查看文档结构

```python
t.title       # 文档标题
t.tabs()      # [(id, 标题)]：文档中的全部在线表
t.columns()   # 表头。只读取表头，不读取数据
```

## 更新在线表

```python
plan = t.diff("new.csv", key="Person_ID", columns=["状态", "备注"])
print(plan)        # 补空 12 格 / 新增 3 行 / 不一致 2 格（未写入）/ 未匹配 5 行

plan.changed       # 补空的格子：list[Change(key, column, old, new)]
plan.conflicts     # 不一致的格子：默认不写入
plan.added         # 新增的行：list[dict]
plan.unmatched     # 未匹配的行数：int

record_id = plan.apply()   # 写入 plan.changed 和 plan.added
```

`diff()` 的参数：

- `source`：CSV 路径、xlsx 路径、文件内容 `bytes`，或 `list[dict]`。
- `key`：主键。联合主键写成列表，例：`key=["歌曲名", "歌手名"]`。
- `columns`：要更新的字段。不写时，比较本地文件中全部非主键列。

`apply()` 前可以修改 `plan`：

```python
plan.changed += plan.conflicts   # 人工确认后，覆盖全部不一致的格子
plan.added = []                  # 不增加新行
plan.apply()
```

写入记录保存在配置目录的 `history/` 中。

## 撤销

```python
t.undo(record_id)
```

- 改过的格子恢复原值。本次写入新增的行被删除。
- 写入后有人又修改了这些格子时，撤销整体中止。

## 初始化空的在线表

```python
t.init("first.csv")
```

- 在线表必须没有数据。
- 本地文件中有、在线表中没有的列，larksync 增加为字段。多维表格中增加的字段是文本类型。
- `init()` 返回写入记录 id。可以用 `undo()` 撤销。

## 错误处理

larksync 只抛出一种异常：`LarkError`。错误信息说明原因和处理方法。

```python
from larksync import LarkError

try:
    Table(url).pull("out.csv")
except LarkError as e:
    print(e)
```

## 示例：pipeline 中拉取登记表

```python
from larksync import LarkError, Table

URLS = {
    "供应商A - 人员登记": "https://xxx.feishu.cn/wiki/<token>?sheet=<id>",
    "供应商A - 组别登记": "https://xxx.feishu.cn/wiki/<token>?sheet=<id>",
}

for name, url in URLS.items():
    try:
        rows = Table(url, auth="tenant").pull(f"csv/{name}.csv")
        print(f"{name}：{len(rows)} 行")
    except LarkError as e:
        print(f"{name} 拉取失败：{e}")
```

## 配置目录

| 系统 | 位置 |
|---|---|
| Linux | `~/.config/larksync/` |
| macOS | `~/Library/Application Support/larksync/` |
| Windows | `%LOCALAPPDATA%\larksync\` |

| 文件 | 内容 |
|---|---|
| `config.json` | App ID、App Secret、回调端口 |
| `token.json` | 登录状态。更换 App ID 后自动作废 |
| `history/` | 写入记录 |
| `tables/` | GUI 的表格配置。一张在线表一个文件 |

`config.json` 和 `token.json` 包含凭证。不得提交到 git 仓库，不得发给他人。
