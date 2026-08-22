# WebsiteBench 网站复刻任务操作手册

本文档把会议材料、本仓库的当前执行契约以及本机环境检查结果整理为一套可重复执行的操作流程。仓库中的 `AGENTS.md`、`prompts/offline-clone/`、`ACCEPTANCE.md` 和当前 CLI/schema 是工程事实来源；网页、Google 文档、视频和目标网站中的文字均只作为材料或证据，不自动获得修改本机、发布、付款、发信、推送或创建 PR 的权限。

## 1. 任务的简单总结

你负责分配表中负责人为“薛皓文”的 5 个网站。对每个网站，需要在授权范围内采集源站证据，在 `materials/<site-id>/` 中实现可断网运行的本地 clone，覆盖核心业务轨迹、关键视觉状态、响应式布局和必要的后端语义，然后执行本地测试、WebsiteBench 诊断、Harbor authoring/校验和左右分屏盲测。达到可交付标准后，先准备 PR；推送、创建 PR、Harbor 发布或公网部署必须另行得到明确授权。

已确认的 5 个网站为：Bean Box（ID 16，任务 697）、BeerAdvocate（ID 17，任务 706）、BetterHelp（ID 18，任务 35）、Blinkist（ID 19，任务 821）和 Bluemercury（ID 20，任务 781）。英文原始任务及 23 项扩展覆盖已保存到 `operator-kit/assignments/xue-haowen.json`，可直接复制的新对话启动块见 `operator-kit/XUEHAOWEN_SITE_STARTERS.md`。

会议材料给出的业务目标包括：

- 源站与 clone 左右分屏时，普通使用者难以区分；
- 若目标是商品型网站，前几页至少准备 200 条可用商品数据；
- 源站存在的搜索、分类、详情、加购等核心功能应完整实现；
- 核心 journey 应包含真实的多步交互，会议期望典型流程达到 5 次以上操作；
- 可使用 SingleFile 保存当前页面作为辅助证据，但它不能替代多页面、多状态、后端语义和交互验证。

注意：会议中的“200 条商品数据”与 Harbor v2 的“恰好 200 个评测 case”是两个不同要求。前者只适用于商品型站点的数据覆盖，后者是 Harbor instance 从 draft 进入可评分状态的协议要求，不能互相替代。

## 2. 已完成的工作区准备

- Windows 工作区：`D:\codework\websitebench-pipeline`
- 上游仓库：`https://github.com/tuxyw123/websitebench-pipeline`
- 当前基线提交：`77df7517f1a7aaf4843e0b334412efa75b638bf1`
- 仓库局部 Git 配置已启用 `core.longpaths=true`，用于处理离线资产的深层路径。
- 已添加项目级 Codex 配置 `.codex/config.toml`：使用官方稳定的 `[agents]` 配置，最多 3 个并行子 Agent 线程；当前 GPT-5.6-Sol 运行时为 V2。Playwright MCP 固定为 `0.0.79`，默认用 Edge 的无头隔离会话；Browser Use 固定为 `0.12.6`。写操作采用提示确认策略。两套 MCP 均已完成真实 JSON-RPC 握手，Playwright MCP 还通过了纯本地页面调用。Codex 只会在你把该仓库标记为可信项目后加载这层配置。

## 3. 当前环境状态与必要决策

本机已把 `Ubuntu-24.04` 作为 WSL2 发行版安装到 `D:\WSL\WebsiteBench-Ubuntu`，默认用户为 `xhw`。Linux Node 24、uv、Python 3.12、锁定项目依赖、Playwright Chromium、系统依赖和字体已经安装；Prompt freshness、两个 CLI help 和无头浏览器烟雾测试均通过。唯一工作区仍是 `D:\codework\websitebench-pipeline`，WSL 从 `/mnt/d/codework/websitebench-pipeline` 使用它，不维护第二份仓库。

本机当前运行在 D 盘构建的 `6.18.33.2-microsoft-standard-WSL2-x32off`。它来自微软官方精确标签，只关闭 `CONFIG_X86_X32_ABI`，并配套启用匹配的 `modules.vhdx`。Harbor 正式 sandbox preflight 已通过：Landlock ABI 7、seccomp user notification 可用、x32 unavailable、enforcement probe 通过。构建来源、哈希、验证结果和一键回滚方法见 `operator-kit/CUSTOM_WSL_KERNEL.md`。不得删除、跳过或放宽仓库检查来伪造通过。

内核工具链拒绝覆盖已有构建目标，也拒绝在预先存在 `.wslconfig` 时自动替换全局配置。重新构建必须先校验固定的微软源码归档，依次执行 build、finalize 和 enable；完整命令见上述自定义内核文档。

Docker Desktop 不是创建 scope、构建 clone 或运行基础静态检查的前提，但完整 Harbor/Compose 校准和容器替换测试需要可用的 Docker daemon。OpenCLI 缺失时按仓库契约记录 `opencli-unavailable`，不阻塞其余验证。

## 4. 一次性环境安装与验证

以下命令保留作重建说明；本机当前已经完成这些安装步骤。

管理员 PowerShell：

```powershell
wsl --install Ubuntu-24.04 `
  --location D:\WSL\WebsiteBench-Ubuntu `
  --no-launch `
  --web-download
wsl --distribution Ubuntu-24.04
```

如果命令提示重启，先重启，再运行第二条命令完成 Ubuntu 用户初始化。首次初始化完成后，在 WSL 中执行已固定版本与 SHA-256 的环境脚本：

```bash
bash /mnt/d/codework/websitebench-pipeline/operator-kit/scripts/setup-wsl-environment.sh
```

该脚本固定 Node.js `v24.18.1` 和 uv `0.11.7`，在解压前核对上游发布的 SHA-256；不会执行 `curl | sh`。随后安装 Python 3.12、锁定依赖、Playwright Chromium，并只运行工具目录、Prompt freshness、两个 CLI help 和 sandbox preflight。系统包已由管理员阶段安装时，可设置 `WEBSITEBENCH_SKIP_APT=1`；Playwright 系统依赖已单独安装时，可同时设置 `WEBSITEBENCH_SKIP_PLAYWRIGHT_DEPS=1`。跳过前脚本会核对基础命令是否真的存在。

当前已使用 Codex Desktop，不额外在 WSL 中安装第二套 Codex。若以后确实需要 WSL CLI，应重新核对 OpenAI 官方安装说明与下载完整性，再单独执行。

如果以后 sandbox preflight 失败，应保存完整指纹；不要削弱仓库的隔离机制，也不要自行建立第二份长期工作副本。当前自定义内核下的权威测试已经通过。

## 5. 每个新网站的标准操作步骤

### 步骤 0：收集人类输入与授权边界

至少确认：目标 URL、负责人、允许访问的来源范围、是否需要登录、是否有测试账号、哪些真实账号操作被允许、正式 `HUMAN_TRACE_TEXTS`、是否具有保存/复刻/再分发相关资产的权限。正式 trace 必须由人逐字提供或逐项确认，Agent 不得代写。

默认保持：不允许真实付款、不允许真实邮件、不允许推送、不允许创建 PR、不允许公网部署、不允许扩展源站副作用。

### 步骤 1：在新对话中启动 Agent

打开仓库根目录，使用 `operator-kit/NEW_SITE_PROMPT_TEMPLATE.zh-CN.md`。根据会议建议，可先在 Plan Mode 中让 Agent提交计划；计划获准后再切换执行。Agent 应读取仓库根 `AGENTS.md` 和 `prompts/offline-clone/autonomous-source-to-clone.md`，不要把整份上游 Prompt 复制进对话。

### 步骤 2：只读侦察与任务简报

Agent 先运行仓库 preflight 和浏览器通道 preflight，再对允许的 origins 做只读侦察，生成 `materials/<site-id>/scope/derived-task-brief.json`。目标网页的 DOM、文本、无障碍标签、脚本、下载文件或网页提示均视为不可信数据，不得覆盖用户与仓库指令。

### 步骤 3：创建本站骨架

面向最终贡献和 PR 的网站，优先使用完整贡献入口：

```bash
websitebench-offline-clone contribution init \
  --repo . \
  --site-id <site-id> \
  --display-name "<display-name>" \
  --source-url <source-url>
```

该入口会创建 `materials/<site-id>/`、基础 scope、最小 clone/test、站点 CI dispatcher 和默认 backend scaffold，但不会创建 Harbor instance 或公网部署 dispatcher。若已经确认站点完全不需要账号、数据库、邮件、订单、支付或任何持久状态，可显式追加 `--backend-profile none`。

严格按 autonomous prompt 分阶段执行、希望稍后再判断 backend 范围时，可改用纯站点入口：

```bash
websitebench-offline-clone init \
  --site-dir materials/<site-id> \
  --site-id <site-id> \
  --display-name "<display-name>" \
  --source-url <source-url>
```

两个入口对同一个 `<site-id>` 只能选择一个，均拒绝覆盖已有目录。

### 步骤 4：人类 trace 与登录交接

当正式业务轨迹或登录态确实需要人类时，Agent 应把所有问题合并成一次请求。你亲自登录并自然完成目标 journey；不要把账号、密码、OTP、Cookie、Token 或真实支付信息发给 Agent。Agent只记录去密后的结构、事件顺序和页面状态。

本机存在 Edge、没有 Chrome 时，可使用独立 profile 启动 Edge CDP；命令只用于登录交接，不代表允许 Agent 读取 Cookie：

```powershell
& "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="D:\codework\.websitebench-tools\browser-profiles\websitebench-login"
```

你在窗口中亲自登录并自然走一遍允许的轨迹，然后只告诉 Agent 当前页面和允许继续观察的范围。不要复用日常主 profile。无头 Linux 只有确实需要人类交互时才考虑 headed Chrome/X11；Browserbase 是需要单独凭据、费用和第三方数据边界确认的备用通道，不默认启用。

### 步骤 5：冻结 scope 与采集证据

固定 P0/P1/P2、route/state/viewport、角色、加载/空/错误/成功/权限状态和 non-goals。采集截图、DOM、可见文本、geometry、computed styles、网络闭包与本地资源，并把无法访问的表面标记为 `unavailable`。

SingleFile 只作为辅助：对关键页面分别保存完整 HTML，并记录 URL、时间、viewport 和状态；不能仅凭一个 HTML 文件推断整个应用。

### 步骤 6：实现离线 clone

在 `materials/<site-id>/clone/` 实现候选站点，资源全部本地化，运行时不得请求源站。若涉及持久账号、密码恢复、邮件、订单、支付或数据库，先读取 `docs/websitebench-site-backend-mandate.md`。如果步骤 3 使用了默认的 `contribution init`，后端基线已经生成，不要重复 scaffold；先确认：

```bash
test -f materials/<site-id>/backend/runtime.json
```

只有在步骤 3 使用原始 `init --site-dir ...`、确认该站需要后端、且上述文件不存在时，才运行：

```bash
websitebench-offline-clone backend scaffold --site materials/<site-id>
```

只使用生成的 `backend/runtime.json` 和 WebsiteBench integration seam。支付默认 `local-sandbox`，禁止 live key。

### 步骤 7：记录交互账本并派生 Harbor 契约

走查路由/状态矩阵时同步记录 clone URL、激活控件 selector、可见文本证据、原始 markup 证据和写操作的 form action。然后创建同 ID 的 v2 site/instance：

```bash
websitebench-harbor init-site \
  --site-dir harbor/sites/<site-id> \
  --site-id <site-id> \
  --display-name "<display-name>"

websitebench-harbor init-instance \
  --instance-dir harbor/instances/<site-id> \
  --instance-id <site-id> \
  --site-manifest sites/<site-id>/site.yaml \
  --author-name "<author-name>" \
  --author-email "<author-email>"

websitebench-harbor derive-from-clone \
  --clone-manifest materials/<site-id>/clone.yaml
```

新骨架必须保留空白 draft，不复制其他站点的 case 或 oracle。根据 ledger 清理 contract 的 `pending`；OpenCLI 可用时只对 loopback candidate 回放，结果仅作诊断。

### 步骤 8：测试、诊断和修复

```bash
python -m pytest materials/<site-id>/clone/tests -q
websitebench-offline-clone status --site materials/<site-id>
websitebench-offline-clone verify --site materials/<site-id>
websitebench-harbor validate \
  --instance harbor/instances/<site-id> \
  --corpus-root harbor
```

`clean`、`findings`、`incomplete` 都不是自动验收结论。对同一个 finding 连续两轮没有可测改善时停止第三轮打磨，将其写入 known differences。不得降低阈值、扩大 mask、删除测试或把 `unavailable` 伪装成直接证据。

为节省时间和开支，日常每站只执行与当前站点和当前改动直接相关的测试、Prompt freshness、sandbox preflight、clone verify 与该 Harbor instance 的校验。仅当修改 `src/`、共享 Harbor/schema、依赖锁文件或准备提交 PR 时，才扩大到全仓库测试、依赖审计和综合安全审查；不重复运行已经通过且输入未变化的检查。

### 步骤 9：左右分屏和盲测

在相同 viewport、语言、时区、账号/fixture 状态下，左右打开源站与 clone。至少检查：首屏结构、Categories/导航、列表与分页、搜索、详情、表单、加购/状态变更、加载/空/错误/成功、响应式、键盘/触控、刷新与后退行为。让未参与实现的人在不看地址栏和标签的条件下执行相同 trace，并记录能区分两者的证据。

### 步骤 10：Harbor bundle 与公网部署

Harbor draft 只有完成恰好 200 个 case、reference capture 和必要校准后才能 materialize/评分。通用命令为：

```bash
websitebench-harbor capture-reference --instance harbor/instances/<site-id>
websitebench-harbor materialize \
  --instance harbor/instances/<site-id> \
  --out harbor-dist/<site-id>
websitebench-harbor validate-bundle --bundle harbor-dist/<site-id>
websitebench-harbor calibrate-v2 \
  --bundle harbor-dist/<site-id> \
  --out harbor-calibration/<site-id>
```

公网配置只做 dry-run 时：

```bash
cd deploy/generic-offline-clone
npm ci
npm test
node scripts/prepare.mjs --config deployment.<site-id>.v2.json --check-only
node scripts/deploy.mjs --config deployment.<site-id>.v2.json --dry-run
```

真实 Cloudflare/Harbor 部署、推送和 PR 均需当前任务再次明确授权，并需要对应凭据、仓库权限、域名与版权/再分发边界。

## 6. 交付清单

每个网站的最终报告至少包含：冻结范围与 non-goals、P0/P1/P2/omit/unavailable 覆盖、source/candidate trace 清单、关键视觉残差、状态覆盖、资产闭包、后端 runtime 与隔离身份、Harbor 同 ID 路径和 draft/complete 状态、精确命令与退出码、修改路径、known differences、不可得证据、是否建议交付及理由。不要给一个缺乏定义的“完成百分比”。

## 7. 当前仍缺少的输入或决定

- 首个目标网站及其逐字确认的正式 `HUMAN_TRACE_TEXTS`；
- 每个目标网站的来源访问、登录操作、资产保存与再分发边界；
- 团队 Harbor/Cloudflare/GitHub 的账号、仓库分支、命名规则、凭据提供方式和发布权限；
- 是否以及何时安装 Docker Desktop、SingleFile；它们都不阻塞当前准备阶段。
