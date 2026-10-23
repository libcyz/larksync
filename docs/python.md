# Python 调用

术语和更新规则见 [README](../README.md)。

## 安装

```bash
pip install larksync      # 需要 Python 3.10+
```

## 快速开始

```python
import larksync
from larksync import Table

larksync.configure("cli_xxx", "app_secret")    # 每台机器运行一次

t = Table("https://xxx.feishu.cn/wiki/<token>?sheet=<id>")

rows = t.pull("out.csv")         # 拉取：返回 list[dict]，同时写入 CSV

plan = t.diff("new.csv", key="ID")
print(plan)                      # 补空 12 格 / 新增 3 行 / 不一致 2 格（未写入）/ 未匹配 5 行
record_id = plan.apply()         # 写入

t.undo(record_id)                # 撤销这次写入
```

首次运行时打开浏览器授权。之后 larksync 自动续期。

## API

| 调用 | 说明 |
|---|---|
| `Table(url, auth="user", tab=None)` | 打开在线表。支持 `/wiki/`、`/sheets/`、`/base/` 链接 |
| `t.pull(path=None)` | 拉取全部行，返回 `list[dict]`。传 `path` 时同时写入 CSV |
| `t.columns()` | 表头 |
| `t.tabs()` | 文档中的全部在线表：`[(id, 标题)]` |
| `t.title` | 文档标题 |
| `t.diff(source, key, columns=None)` | 和本地数据比较，返回 `Plan` |
| `plan.apply()` | 写入，返回写入记录 id |
| `t.undo(record_id)` | 撤销一次写入 |
| `t.init(source)` | 用本地文件初始化空的在线表 |

- `tab`：指定在线表 id。不写时，用链接中的 `?sheet=` / `?table=`；链接也没有时，用第一张在线表。
- `source`：CSV 或 xlsx 的路径、文件内容 `bytes`，或 `list[dict]`。CSV 可以是 UTF-8 或 GBK。
- `key`：主键。联合主键写成列表：`key=["歌曲名", "歌手名"]`。
- `columns`：要更新的字段。不写时，更新本地数据中全部非主键列。

### Plan

| 属性 | 内容 | `apply()` 时 |
|---|---|---|
| `plan.changed` | 补空的格子 | 写入 |
| `plan.conflicts` | 不一致的格子 | 不写入 |
| `plan.added` | 新增的行 | 写入 |
| `plan.unmatched` | 未匹配的行数 | — |

`apply()` 前可以修改 `plan`：

```python
plan.changed += plan.conflicts   # 确认后，覆盖不一致的格子
plan.added = []                  # 不新增行
plan.apply()
```

## 在服务器上运行

服务器没有浏览器。用 tenant 身份，凭证放在环境变量中：

```bash
export LARKSYNC_APP_ID=cli_xxx
export LARKSYNC_APP_SECRET=xxx
```

```python
Table(url, auth="tenant").pull("out.csv")
```

- tenant 身份必须把应用加为在线表的协作者。
- 要用 user 身份：在有浏览器的机器上登录一次，把配置目录中的 `config.json` 和 `token.json` 复制到服务器。

## 示例：pipeline 中批量拉取

```python
from larksync import LarkError, Table

URLS = {
    "人员登记": "https://xxx.feishu.cn/wiki/<token>?sheet=<id>",
    "组别登记": "https://xxx.feishu.cn/wiki/<token>?sheet=<id>",
}

for name, url in URLS.items():
    try:
        rows = Table(url, auth="tenant").pull(f"csv/{name}.csv")
        print(f"{name}：{len(rows)} 行")
    except LarkError as e:       # larksync 只抛出这一种异常，错误信息包含处理方法
        print(f"{name} 拉取失败：{e}")
```

## 配置目录

- Linux：`~/.config/larksync/`
- macOS：`~/Library/Application Support/larksync/`
- Windows：`%LOCALAPPDATA%\larksync\`

目录中有 `config.json`（应用凭证）、`token.json`（登录状态）和 `history/`（写入记录）。`config.json` 和 `token.json` 不得提交到 git 仓库。
