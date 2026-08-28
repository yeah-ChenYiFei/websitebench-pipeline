# websitebench-pipeline — WebsiteBench 离线网站复刻流水线

本仓库包含 WebsiteBench 的配置驱动生产流水线，覆盖范围定义、源证据采集、
离线网站 clone、机器诊断、Harbor interaction contract 与评测 instance。诊断
结果是维护者判断的输入。

## 公开导出范围

这个 public repository 仅发布可再分发的流水线代码、schemas、通用工具、文档和
站点无关测试。内部金样本 TripIt 的抓取证据、镜像 clone、Harbor reference /
instance，以及站点专属部署配置未包含在公开导出中：该样本的权利审查明确没有
授予 TripIt / Concur / SAP 商标、页面内容、图片和字体的公开再分发许可。

如需使用流水线，请从自己的、已获授权的目标站点创建新材料目录；不要把源站
访问凭据、cookie、授权头、支付数据或敏感表单值写入仓库、日志或证据产物。

## 快速开始

普通贡献者只需要克隆 `main`；每个网站保存在同一仓库自己的持久分支
`sites/<site-id>`。必须使用 `--single-branch`，否则普通 `git clone` 仍会获取其他
站点分支的对象。

```bash
git clone --single-branch --branch main --filter=blob:none --depth=1 \
  https://github.com/780078268/websitebench-pipeline.git
cd websitebench-pipeline
python scripts/site_workspace.py list
python scripts/site_workspace.py command <site-id>
# 或从 main checkout 旁边只展开一个站点 worktree：
python scripts/site_workspace.py checkout <site-id>
```

站点 worktree 中仍使用 `materials/<material-id>`，现有诊断和运行命令保持不变。
站点 PR 必须以对应的 `sites/<site-id>` 为 base；Pipeline PR 才以 `main` 为 base。
详细迁移、贡献与 review 流程见
[`docs/per-site-repository-workflow.md`](docs/per-site-repository-workflow.md)；
可直接转发给贡献者的中文简版见
[`docs/website-contribution-quickstart-zh.md`](docs/website-contribution-quickstart-zh.md)。

Agent 在创建站点材料前，先读 `AGENTS.md` 与
`docs/source-evidence-access-policy.md`。
新站的 Harbor v2 authoring 必须通过 `websitebench-harbor init-site` 与
`init-instance` 建立严格同 ID 的 pair。新骨架是 compile-executable v2 空白
draft；完成 case、oracle 与校准证据前不可 capture、materialize、calibrate 或评分。

```bash
# Python >= 3.11
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m playwright install chromium

# 修复被删除或损坏的 .venv（WSL/Linux；也可设置 UV_BIN 指定 uv 路径）
./scripts/bootstrap_env.sh

# 查看通用离线 clone 工具
python tools/offline_clone/run.py tools list

# 创建一个新站点骨架
websitebench-offline-clone contribution init \
  --repo . \
  --site-id <site-id> \
  --display-name "<Name>" \
  --source-url https://example.test/

# 对站点运行静态与浏览器诊断
websitebench-offline-clone verify --site materials/<site-id>
```

## 流程入口

- `prompts/offline-clone/RUNBOOK.md`：人类发起任务和提供授权范围的入口。
- `prompts/offline-clone/autonomous-source-to-clone.md`：agent 执行契约。
- `ACCEPTANCE.md`：分阶段人工/agent 验收清单。
- `AGENTS.md`：仓库安全、命名、证据与后端约束。
- `docs/source-evidence-access-policy.md`：真实站点证据采集政策。

核心目录：

- `src/websitebench/`：CLI 与 Python 库。
- `websitebench/`：schemas、capability packs 与 corpus 元数据。
- `tools/offline_clone/`：跨站诊断工具。
- `deploy/generic-offline-clone/`：通用 public-demo 部署包。
- `harbor/`：Harbor schemas 与通用运行时。
- `tests/`：站点无关自检。

## Agent 如何读懂仓库并与人协作复刻

先建立三层心智模型：`materials/<site-id>/` 保存某个站点的事实、scope、证据、
clone 与测试；`src/websitebench/` 和 `tools/offline_clone/` 提供所有站点共用的
执行与诊断能力；`prompts/`、`docs/` 和 `ACCEPTANCE.md` 规定 agent 怎么工作、
人怎么根据证据作判断。新增站点应主要增加配置和材料，而不是复制一套站点专属
诊断代码。

### 最短阅读路径

1. 先读 `AGENTS.md` 和 `docs/source-evidence-access-policy.md`。在动手前，agent
   应能复述允许访问的 origins、可用 session、敏感信息边界、外部副作用和发布
   权限；缺失的权限不能由机器结果补足。
2. 读 `prompts/offline-clone/RUNBOOK.md` 了解人类如何发起任务，再读
   `prompts/offline-clone/autonomous-source-to-clone.md` 了解 agent 的阶段、停止
   条件和按需 reference。不要一开始遍历所有源码。
3. 运行 `python tools/offline_clone/run.py tools list`，再从相关命令的 `--help`、
   `src/websitebench/offline_clone/` 和对应的 `tests/offline_clone/` 追踪真实行为。
   CLI、schema、测试和当前目录结构是实现事实的来源。
4. 用 `contribution init` 创建站点骨架，先读生成的 `clone.yaml` 与 `scope/`。
   路由、状态、viewport、匿名诊断无法到达的状态配方等站点知识写入材料目录；
   通用能力才进入 `src/` 或 `tools/`。
5. 实现时以 `prompts/offline-clone/build.md` 为顺序，以 `ACCEPTANCE.md` 为人类
   验收视角。更完整的代码库导览见
   [`docs/codebase-offline-site-clone-workflow-zh.md`](docs/codebase-offline-site-clone-workflow-zh.md)。

历史 v1 site/instance 只承担兼容身份，不能作为新站的 Harbor 布局、测试内容或
评分协议模板；新站以当前 prompt 和 CLI 生成的 compile-executable v2 draft 为准。

### 人与 agent 的协作契约

人类至少提供目标 URL 及允许访问的来源范围；URL 本身不代表抓取授权，agent
也不能从网络事实推断授权。在 agent 基于证据提出需求后，人类再提供登录动作或
会话、权利与公开发布边界，并对可接受差异和最终交付作判断。正式
`human_trace_text` 必须由人逐字提供，或由人逐项确认已有任务文本，agent 只能
另写建议范围，不能代拟或替人确认。登录材料应通过任务环境提供，不进入提交或
证据。

agent 负责把这些输入冻结为可审计的 scope，持续采集去密证据、实现本地 clone、
运行诊断并修复可复现差异。范围内的工程选择、局部修复和重跑不需要逐步等待
人工确认；只有需要人提供正式 trace 或登录、需要扩大授权范围、涉及人的私有
信息，或将产生公网发布、真实消息、真实付款等未授权外部效果时，才把所有当前
问题合并后一次交还给人，并继续处理不依赖答案的工作。

双方使用同一组证据说话：人不需要替 agent 操作浏览器或逐文件指导实现，agent
也不能把 `clean` 当作人的验收、版权判断或发布授权。

### 一次复刻的闭环

```text
授权与范围 → route/state/viewport 证据 → 离线实现 → 交互契约 → 诊断与修复 → 人类判断
```

1. 创建站点骨架，冻结 origins、角色、journey、状态、viewport 与 non-goals。
2. 用配置允许的浏览器路径走查源站并采集截图、DOM、文本、样式、网络与本地资源
   闭包；不可访问的表面如实标为 `unavailable`，同时保证证据不含凭据或用户数据。
3. 在 `materials/<site-id>/clone/` 实现断网可运行的候选，匹配加载、空、错误、
   overlay、响应式、键盘和触控状态。走查矩阵时同步记录 interaction ledger。
4. 若 scope 包含持久账号、邮件、付款、订单或数据库，先读
   `docs/websitebench-site-backend-mandate.md`，再运行 `backend scaffold`，只通过
   生成的 `backend/runtime.json` 集成，并保持每站数据和 session 隔离。
5. 从本轮构建产物派生 Harbor interaction contract，并只对运行在 loopback 的
   本地 clone 做 OpenCLI replay；它是提前发现死路由或失效 selector 的独立诊断，
   其结果不会改写 `verify` 的 `clean` / `findings` / `incomplete` 状态。
6. 每次修改先跑窄测试，稳定后运行站点测试和
   `websitebench-offline-clone verify --site materials/<site-id>`。依据 findings 修复
   后重跑；同一 finding 连续两轮没有可测改善、源证据不稳定或只能由人提供却
   无法取得时，按执行契约停止打磨并诚实登记。P0 可用且所有缺口已列出后，由
   维护者判断是否交付；P0 尚不可用时同样交付当前证据和报告，但必须明确标为
   “尚不可交付”，不能无限等待或声称已完成。
7. 如果任务还要求 Harbor benchmark，再按完整流程为站点创建唯一同 id instance
   并验证 bundle；单纯交付本地 clone 时，不要把评测或公网部署默认为授权范围。

agent 的最终交付应列出：冻结的范围与未覆盖表面、改动路径、精确命令及结果、
当前 `clean` / `findings` / `incomplete` 状态、已知差异、不可得证据；涉及后端时
还要报告 runtime 路径、唯一 `site_id`、数据库/卷身份、邮件用途、付款与部署
profile。这样人类可以复现证据并作判断，而不是只接收一句“已经完成”。

## 安全边界

- 源站探索默认只读；没有精确场景与显式授权时不发送非 GET 请求。
- clone 诊断是 `diagnostic-only`，不能替代版权、再分发或部署授权。
- 后端、邮件与支付能力必须使用仓库生成的 runtime contract；live payment
  credentials 永远禁止。
- 公网发布必须使用固定的单站 dispatcher，并由人明确授权。

## License

仓库自有代码按 [Apache License 2.0](LICENSE) 发布。第三方名称、商标、内容与
资产仍归各自权利人所有；Apache-2.0 不会为它们额外授予权利。
