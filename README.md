# websitebench-pipeline — 离线网站复刻流水线

本仓库是从 WebsiteBench 主仓库抽离出来的**生产流水线**：从一句 prompt 出发，
批量生成高保真离线网站 clone。一次获得完整范围与发布授权的生产，**最终产出物
有两个**：

1. Harbor 格式标准的评测 instance（`harbor/instances/<site-id>/`）；
2. 部署成功的公网演示站（`https://<site-id>.website-bench.com`，Basic-auth
   门禁 + noindex）。

只提供启动 prompt 不会授权公网发布；没有明确发布授权时，流程停留在本地 clone、
Harbor 产物与部署准备。

这是一个**人类与 agent（Claude Code）协作**的 codebase：

| 角色 | 关注点 | 入口 |
| --- | --- | --- |
| 人类 | 发起任务、提供授权与源访问、**验收**、批准公网发布 | 本文件 + `ACCEPTANCE.md` + `prompts/offline-clone/RUNBOOK.md` |
| Claude Code | **执行**：取证 → 构建 → 校验 → 后端 → Harbor 契约 → instance → 部署准备；获明确授权后发布 | `CLAUDE.md` + `AGENTS.md` + `prompts/offline-clone/` |

## 一次新站生产长什么样

1. **人**：按 `prompts/offline-clone/RUNBOOK.md` 用一个目标网址起任务；可以选择
   在启动时附上自己写的 P0/P1 业务轨迹。需要登录时，由 Agent 汇总证据缺口后
   请求人类在本机浏览器完成登录与自然操作。
2. **Agent**：以 `prompts/offline-clone/autonomous-source-to-clone.md` 为操作
   契约自主执行 12 个阶段（此处合并概述）：范围冻结 → 源证据采集 → 资产闭包
   → 前端路由/状态矩阵 → 交互台账 → 后端语义 → 诊断修复 → Harbor 契约派生
   → 部署准备。
3. **人**：按 `ACCEPTANCE.md` 分阶段验收。机器诊断（`clean/findings/incomplete`）
   永远只是输入，验收决定由人做出。
4. **Agent**：用 `websitebench-harbor init-site` 与 `init-instance` 建立严格同 ID
   的 Harbor v2 authoring pair。新骨架只生成空白 draft case/task/visual/CI/CD
   文件；它可校验但不可 capture、materialize、calibrate 或评分。后续再由人与
   agent 基于站点证据完成恰好 200 项 case、oracle 与校准证据。
5. **人**：显式授权公网发布后，**agent** 走 `deploy-<site>-public.yml`
   （`deploy=true`）发布并按 `references/08-deploy.md` 在线复检；未授权前
   只允许 `--check-only` / `--dry-run`。

## 人类快速上手（约 5 分钟）

前置条件：Python 3.11+ 和 `uv`。完整源站采集还需要可用的 Chrome/Chromium；
启用浏览器 MCP 时还需 Node.js/npm（用于 `npx`）。以下命令假设你已经取得
checkout 并进入仓库根目录：

```bash
# 1. 创建环境并安装 WebsiteBench CLI 与开发依赖
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m playwright install chromium

# 2. 确认 prompt 与当前代码一致，并列出可用的跨站诊断工具
python -m pytest tests/test_prompt_freshness.py -q
python tools/offline_clone/run.py tools list

# 3. 用金样本 tripit 验证安装；先跑不需要启动浏览器的 static 分区
websitebench-offline-clone status --site materials/tripit
websitebench-offline-clone verify --site materials/tripit --section static
```

`verify` 只输出诊断报告：`clean`、`findings` 或 `incomplete`。它不代替人的
验收，也不授予复制、再分发或部署权限。完整的人类操作说明见
[`prompts/offline-clone/RUNBOOK.md`](prompts/offline-clone/RUNBOOK.md)，交付判断见
[`ACCEPTANCE.md`](ACCEPTANCE.md)。上述命令均成功执行即可确认本地入口可用；
`tripit` 的诊断内容描述的是金样本站点，不是安装是否成功。

如果只想手动创建一个空站点骨架，可以运行：

```bash
websitebench-offline-clone contribution init --repo . --site-id <site-id> \
  --display-name "<Name>" --source-url https://example.test/
```

`site-id` 只能使用小写字母、数字和非连续连字符；骨架写入
`materials/<site-id>/`，同时创建对应的站点诊断 workflow。

使用下一节的完整 Agent prompt 工作流时无需先执行这条命令；Agent 会根据源站
证据推导站点信息并创建所需目录。

## 让 Agent 从一个 URL 开始离线 clone

在 Claude Code（或其他能够读取本仓库并执行命令的 Agent）中打开仓库，只发送
下面这段启动指令。不要把整份 prompt 复制进对话：

```text
Follow prompts/offline-clone/autonomous-source-to-clone.md.
SOURCE_URL=https://example.com
HUMAN_TRACE_TEXTS=[]
```

`SOURCE_URL` 是启动时唯一必填的任务输入。`HUMAN_TRACE_TEXTS` 可以留空；Agent
会先做只读侦察，再根据真实证据缺口一次性请求最少的人类操作轨迹。正式构建前
仍可能需要人提供轨迹、完成登录或明确授权。也可以在启动时直接提供你自己写的
业务目标，减少一次中途交接：

```text
HUMAN_TRACE_TEXTS=["搜索下周三的酒店，选择可免费取消的选项，并继续到确认页。"]
```

轨迹文字必须由人写，且不得包含账号、密码、OTP、cookie、token 或真实支付
信息。无需预先填写 `site-id`、角色、journey、viewport、时区或测试数据；入口
prompt 会要求 Agent 从当前仓库和允许访问的源站证据中推导这些信息。

Agent 随后按 12 个阶段执行（以下为合并概述）：仓库预检与只读侦察 → 生成任务
brief → 获取必要的人类轨迹 → 冻结范围与视觉契约 → 实现前后端 → 生成交互台账
与 Harbor 契约 → 运行诊断和修复 → 准备部署。详细步骤按需从
[`prompts/offline-clone/references/`](prompts/offline-clone/references/) 载入；入口
prompt 始终是操作契约。

人类只在以下边界介入：

- 登录必须由人亲自完成，Agent 不读取或保存凭据与会话密钥；
- 正式轨迹文字必须由人提供或逐项确认；
- 源站写操作、真实邮件、支付、push、PR 和公网部署默认关闭，扩大权限必须由人
  明确授权。
- 范围、证据、测试和诊断是否足以交付，最终由人或维护者判断。

如果 Agent 在阶段之间结束一个 turn，回复 `continue` 即可继续，这不代表流程
失败。运行结束后，先查看 `materials/<site-id>/` 中的范围、证据、clone 与报告，
并运行完整的当前诊断：

```bash
websitebench-offline-clone status --site materials/<site-id>
websitebench-offline-clone verify --site materials/<site-id>
```

完整诊断中，`clean` 表示所有已声明检查完成且未发现差异；`findings` 表示检查已
完成并记录了差异；`incomplete` 表示输入无效或有检查未能完成。三者都不是自动
验收结论。再由维护者结合 `ACCEPTANCE.md` 验收；未明确授权公网发布时，只允许
本地验证、`--check-only` 或 `--dry-run`。

## MCP 与 skills（源证据采集必备）

`.mcp.json` 已注册三个浏览器 MCP 服务器，Claude Code 打开本仓库时会提示启用：

| 服务器 | 用途 | 前置条件 |
| --- | --- | --- |
| `chrome-devtools` | 本地 Chrome DevTools 采集 | 本机 Chrome/Chromium；launcher 自动解析 `chrome-devtools-mcp@1.6.0` |
| `browserbase` | 云端浏览器（对抗风控/地区限制时用） | `export BROWSERBASE_API_KEY=… BROWSERBASE_PROJECT_ID=…`（只走环境变量，永不落盘） |
| `playwright` | Playwright 驱动的采集与回放 | `npx` 可用即可 |

采集技能在 `skills/trace-guided-offline-clone/`（已通过 `.claude/skills/`
符号链接接入 Claude Code），`skills-lock.json` 固定其身份。

## 金样本：tripit

`materials/tripit/` + `harbor/sites/tripit/` 是历史兼容样本；新站不得复制它的
Harbor 布局或测试内容，必须以当前 prompt 和 CLI 生成的 compile-executable v2
空白 draft 为准：

- `materials/tripit/scope/` — 冻结的范围契约、checkpoints、verify.json
- `materials/tripit/source-current/`、`source-assets/` — 源证据与资产闭包
- `materials/tripit/clone/` — 可离线启动的 clone（`python app.py`）+ 自带测试
- `materials/tripit/tools/frontend_samples.json` — Harbor 派生的硬输入
- `harbor/sites/tripit/` — 站点契约、interactions（OpenCLI 契约 + adapters）、
  reference、verifier
- `harbor/instances/tripit/` — 不可改写的 v1 兼容 instance；它只能说明历史身份，
  不能作为新 v2 的 `deploy.sh`、suite 数量或评分协议模板。
- `deploy/generic-offline-clone/deployment.tripit.v2.json` +
  `.github/workflows/deploy-tripit-public.yml` — 部署描述符与 dispatcher；
  线上参照：<https://tripit.website-bench.com>（匿名访问 401 是 Basic-auth
  门禁的预期行为）

## 目录地图

| 路径 | 内容 |
| --- | --- |
| `prompts/offline-clone/` | agent 操作契约（入口 + 分阶段 references + RUNBOOK）|
| `src/websitebench/` | 全部 CLI 与库（offline_clone、harbor、viewer、workflow…）|
| `websitebench/` | schemas、capability packs、corpora 等数据 |
| `materials/<site-id>/` | 每个站点的范围、证据、clone、工具（金样本：tripit）|
| `harbor/sites/`、`harbor/instances/` | Harbor 站点契约与评测 instance |
| `deploy/generic-offline-clone/` | 通用公网部署包（Worker + 容器 + 部署描述符）|
| `tools/offline_clone/` | 跨站诊断工具组（`python tools/offline_clone/run.py tools list`）|
| `skills/`、`.agents/` | 浏览器采集等 agent 技能包 |
| `.mcp.json`、`.claude/skills/` | MCP 服务器注册与 Claude Code skill 接线 |
| `docs/` | 政策、后端强制规范、Harbor 设计、中文全流程说明 |
| `tests/` | 仓库自检（prompt 新鲜度、诊断、Harbor、workflow 等）|
| `.github/workflows/` | 站点无关 CI + 每站一个 dispatcher（`tests-tripit.yml`）|

## 红线（对人与 agent 同样生效）

- 凭据、cookie、会话密钥、支付数据**永不入库**（仓库、日志、截图、证据均含）。
- 机器诊断是 `diagnostic-only`：clean 不等于版权、再分发、部署授权。
- OpenCLI replay 只做参考，永不接入评分或合并条件。
- 历史 ClawBench 标识与 vendored 树是不可变数据身份，不得改名或重生成。

详细验收标准见 `ACCEPTANCE.md`；agent 执行规则见 `AGENTS.md`。
