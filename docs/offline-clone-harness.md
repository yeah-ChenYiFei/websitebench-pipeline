# 离线网站 Clone Harness

本仓库的离线复刻工作由 Agent 自主执行，独立机器验证器提供可复现的诊断证据。
`websitebench-offline-clone` 和 `websitebench-workflow` 负责确定性检查、证据生成
与阶段状态；这些检查是推荐使用的诊断工具，是否完成、是否可以推进仍由
Agent/人工判断，不由单一机器结论强制决定。完整责任边界见
[机器验证指南](source-evidence-access-policy.md)。

真实网站的一方、第三方/外部、内部与登录后页面的媒体、文件和截图均允许且鼓励
采集。助手可向机器验证器索取所需账号或交互式登录，并在该有边界任务期间
持续复用获授权会话；不得把凭据或会话秘密写入仓库或证据。完整规则见
[`source-evidence-access-policy.md`](source-evidence-access-policy.md)。

Harbor OpenCLI 把 Harbor site 的交互契约回放到本地 clone
（`websitebench-harbor run-opencli`，见
[`opencli-contract-replay.md`](opencli-contract-replay.md)）。该路径的对象是仓库
自有的本地 fixture，因此允许仓库 wrapper、CLI 与 schema；其结果同样只作诊断，
不形成 trace coverage，也不单独决定接受、合并或发布。

## 从来源到本地候选

1. 配置站点、允许访问的 origin、P0/P1 journey、角色、
   route/state/viewport 矩阵、外部效果和 non-goal。
2. 使用 `websitebench-workflow acquire-source` 按配置的 JSON spec 采集匿名 GET
   来源；执行器拒绝 origin 越界，并保存 DOM、可见文本、截图、几何、computed
   style、网络记录和内容寻址资源。登录后或交互式页面使用已授权的浏览器
   context 采集，并对凭据、cookie、token 和私密账号数据去密。
3. 使用 `websitebench-offline-clone init` 创建 adapter，关闭本地资源，完成前端、
   后端、持久化、迁移、restart、reset、并发和本地外部效果。
4. 运行通用 `static`/`live` 诊断和本站自己的语义、隔离及 full-stack 测试；输出
   `clean`、`findings` 或 `incomplete`，供维护者判断。
5. 用 `websitebench-harbor derive-from-clone` 从该 clone
   采集得到的 `clone.yaml`、`tools/frontend_samples.json` 与 `scope/*.json`
   直接生成 Harbor interaction contract 和 adapters，再对本地 clone 回放各
   profile。命令返回的 pending 项由 interaction ledger 补齐；派生与回放都是
   诊断辅助。
6. 独立机器诊断在精确 URL/process/container、candidate tree、seed、数据库和
   bundle 上检查浏览器体验与业务语义；差异进入 Agent 修复循环，但机器报告不
   自动得出接受、合并或部署结论。

常用命令：

```bash
websitebench-workflow acquire-source --spec capture.json --out-dir source-current/run-1 --report acquisition.json
websitebench-offline-clone verify --site materials/example
websitebench-offline-clone verify --site materials/example --section static
websitebench-harbor derive-from-clone --clone-manifest materials/example/clone.yaml
websitebench-workflow check-semantics --selection semantic-selection.json
websitebench-workflow check-fullstack --candidate candidate.json
websitebench-offline-clone status --site materials/example
```

## 所有 Agent 共用的诊断工具

保证可用的仓库内入口为 `python tools/offline_clone/run.py tools list`；安装包后的
等价入口是 `websitebench-offline-clone tools list`。其 JSON catalog 可供人或 Agent
自动发现，不需要搜索站点专用 `tools/` 目录。仓库内入口不依赖 editable install，
也不受 Windows 中文 checkout 路径的 `.pth` locale 解码影响。声明式示例位于
`tools/offline_clone/specs/`：

```bash
websitebench-offline-clone tools explore \
  --spec browser-scenario.json --base-url http://127.0.0.1:8000 \
  --environment clone --out clone-browser.json --artifacts-dir clone-browser

websitebench-offline-clone tools compare-functional \
  --source source-browser.json --candidate clone-browser.json \
  --out functional-comparison.json

websitebench-offline-clone tools compare-visual \
  --spec visual-comparison.json --out visual-comparison.json \
  --heatmap-dir visual-heatmaps

websitebench-offline-clone tools test-backend \
  --spec backend-semantic.json --base-url http://127.0.0.1:8000 \
  --out backend-semantic-report.json
```

- `explore` 支持 source/clone selector 映射、点击、输入、键盘、hover、选择、
  等待、可见状态断言和截图；来源非 GET 默认阻断。
- `compare-functional` 比较稳定 step/observation ID、route、可见状态、断言和
  console/network 错误行为。
- `compare-visual` 直接读取 source raster、viewport、region、metric 和非零
  threshold，并重新计算 SSIM、edge F1、色彩直方图和 normalized MAE。
- `test-backend` 为每个 actor 隔离 cookie，支持 JSON Pointer 断言、内存变量捕获、
  forged-ID/idempotent replay 等多步测试，以及 invariant 正反例覆盖。

这些输出的 authority 固定为 diagnostic-only。它们可以成为维护者判断的输入，
但不能单独把任何 site 标记为 accepted 或 technically verified。

## 证据规则

- source claim 标记为 directly observed、structural-only、inferred 或 unavailable；
- required 本地资源满足 downloaded = verified = referenced，运行时远程请求为零；
- P0/P1 coverage 按 route、state、viewport、role、interaction 和失败/恢复路径记录；
- 后端服务端权威覆盖 identity、ownership、authorization、validation、stale、
  duplicate、idempotency、restart、migration、reset 和 concurrency；
- 所有报告记录规范相对路径、结构化内容与精确 runtime identity；
- 不把单一截图分数、测试退出码、Harbor reward 或助手自信当作完整保真结论；
  结论必须覆盖配置矩阵并由独立机器证据共同支持。

每次诊断都是当前 manifest、声明输入和候选内容的纯函数，不保存 attempt 或
历史 pass。公开部署前应阅读当前 Harbor 与机器诊断；诊断本身既不授权也不阻止
部署，secret、payment、部署隔离和发布授权检查仍然 fail closed。

## WebsiteBench 声明式编译

`websitebench-site` 可把 inventory、site profile 和 capability packs 编译为
plan 和 explain 文件。当前活动目标为 `scope`、
`frontend`、`backend`、`release`，其失效边界分别是配置范围、前端保真、后端
语义和机器发布清单。materializer 生成可直接由 Agent 执行和验证的范围计划；
旧 V2 materialization 与 review schema 只用于读取历史证据。

历史目录中仍可能出现旧的分阶段评审命名，用于读取已经产生的哈希绑定证据。
这些兼容标识不是活动指令，不能用于恢复已删除的自动 Reviewer 工作流。
