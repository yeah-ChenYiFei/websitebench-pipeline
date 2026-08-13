# websitebench-pipeline — 离线网站复刻流水线

本仓库是从 WebsiteBench 主仓库抽离出来的**生产流水线**：从一句 prompt 出发，
批量生成高保真离线网站 clone，直到产出可评测的 Harbor 站点契约与 instance。
公网部署不在本仓库范围内（见 `PROVENANCE.md`）。

这是一个**人类与 agent（Claude Code）协作**的 codebase：

| 角色 | 关注点 | 入口 |
| --- | --- | --- |
| 人类 | 发起任务、提供授权与源访问、**验收** | 本文件 + `ACCEPTANCE.md` + `prompts/offline-clone/RUNBOOK.md` |
| Claude Code | **执行**：取证 → 构建 → 校验 → 后端 → Harbor 契约 | `CLAUDE.md` + `AGENTS.md` + `prompts/offline-clone/` |

## 一次新站生产长什么样

1. **人**：按 `prompts/offline-clone/RUNBOOK.md` 起一个任务——给出目标网址、
   范围（P0/P1 journey）、可用的登录会话（如需要）。
2. **Agent**：以 `prompts/offline-clone/autonomous-source-to-clone.md` 为操作
   契约自主执行 10 个阶段：范围冻结 → 源证据采集 → 资产闭包 → 前端路由/状态
   矩阵 → 交互台账 → 后端语义 → 诊断修复 → Harbor 契约派生。
3. **人**：按 `ACCEPTANCE.md` 分阶段验收。机器诊断（`clean/findings/incomplete`）
   永远只是输入，验收决定由人做出。
4. **Agent**：`websitebench-harbor init-instance` 起 instance 骨架，人与 agent
   共同完成任务定义、oracle 与校准证据。

## 快速开始

```bash
# 环境（Python >= 3.11）
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'
python -m playwright install chromium

# 看一眼金样本 tripit 的健康状态
websitebench-offline-clone status --site materials/tripit
websitebench-offline-clone verify --site materials/tripit --section static

# 起一个新站脚手架
websitebench-offline-clone contribution init --repo . --site-id <site-id> \
  --display-name "<Name>" --source-url https://example.test/
```

## 金样本：tripit

`materials/tripit/` + `harbor/sites/tripit/` 是一条完整走通的链路样本，
新站的每个产物都应长成它的形状：

- `materials/tripit/scope/` — 冻结的范围契约、checkpoints、verify.json
- `materials/tripit/source-current/`、`source-assets/` — 源证据与资产闭包
- `materials/tripit/clone/` — 可离线启动的 clone（`python app.py`）+ 自带测试
- `materials/tripit/tools/frontend_samples.json` — Harbor 派生的硬输入
- `harbor/sites/tripit/` — 站点契约、interactions（OpenCLI 契约 + adapters）、
  reference、verifier

Harbor instance 尚未为 tripit 创建；`harbor/instances/README.md` 说明如何用
`websitebench-harbor init-instance` 完成这最后一步。

## 目录地图

| 路径 | 内容 |
| --- | --- |
| `prompts/offline-clone/` | agent 操作契约（入口 + 分阶段 references + RUNBOOK）|
| `src/websitebench/` | 全部 CLI 与库（offline_clone、harbor、viewer、workflow…）|
| `websitebench/` | schemas、capability packs、corpora 等数据 |
| `materials/<site-id>/` | 每个站点的范围、证据、clone、工具（金样本：tripit）|
| `harbor/sites/`、`harbor/instances/` | Harbor 站点契约与评测 instance |
| `tools/offline_clone/` | 跨站诊断工具组（`python tools/offline_clone/run.py tools list`）|
| `skills/`、`.agents/` | 浏览器采集等 agent 技能包 |
| `docs/` | 政策、后端强制规范、Harbor 设计、中文全流程说明 |
| `tests/` | 仓库自检（prompt 新鲜度、诊断、Harbor、workflow 等）|
| `.github/workflows/` | 站点无关 CI + 每站一个 dispatcher（`tests-tripit.yml`）|

## 红线（对人与 agent 同样生效）

- 凭据、cookie、会话密钥、支付数据**永不入库**（仓库、日志、截图、证据均含）。
- 机器诊断是 `diagnostic-only`：clean 不等于版权、再分发、部署授权。
- OpenCLI replay 只做参考，永不接入评分或合并条件。
- 历史 ClawBench 标识与 vendored 树是不可变数据身份，不得改名或重生成。

详细验收标准见 `ACCEPTANCE.md`；agent 执行规则见 `AGENTS.md`。
