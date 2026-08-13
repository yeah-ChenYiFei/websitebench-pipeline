# Codebase 离线网站复刻全流程

> 本仓库范围说明：此文档描述完整流程，其中“公网部署”阶段不在本仓库范围内。
> 本仓库（websitebench-pipeline）覆盖到 Harbor 契约与 instance 生成为止；
> 部署相关的 workflow、脚本与文档保留在母仓库中。

当前 codebase 覆盖“选网址 → 固定来源证据 → 本地复刻 → 自动校准 → Harbor
评测 → 公网部署”。机器检查生成可复现的诊断与评分证据；clone 是否合格、是否
合并仍需维护者综合判断。权利与真实外部部署继续遵守任务授权和安全边界。

## 1. 选择与冻结范围

机器验证器确定站点、first-party origins、核心目的、P0/P1 journey、角色、
route/state/viewport、允许的本地模拟、外部效果和 non-goal。声明式场景可先用
`websitebench-site check/compile/explain/materialize` 读取通用 Platform Inventory v2、
profile 与 capability pack，但 inferred 分类不能替代来源事实。

## 2. Source acquisition

真实网站的一方、第三方/外部、内部及登录后页面均允许且鼓励采集媒体、其他文件
和截图；来源类别或需要登录本身不构成缺证理由。使用任务已提供的登录会话；
负责人索取账号或交互式登录，获授权后可在该有边界任务期间持续复用会话，直至
被撤销、过期或任务结束。凭据和会话秘密不得写入仓库或证据，完整边界见
[`source-evidence-access-policy.md`](source-evidence-access-policy.md)。

为 `websitebench-workflow acquire-source` 编写配置驱动的 spec。每行声明 URL、
priority、viewport 和允许 origins；执行器使用隔离 Chrome context、只发 GET，
保存 screenshot、DOM、visible text、geometry、computed style、network log 和
本地资源闭包，并生成内容寻址 v2 report。输出只能证明“采集到了什么”，不能
单独接受保真度。该命令当前只覆盖匿名 GET 行；登录后或交互式证据使用已授权的
浏览器采集路径，并保存去密后的 runtime/context 身份。

Harbor OpenCLI 仅把交互契约回放到本仓库自有的本地 clone
（`websitebench-harbor run-opencli`，见
[`opencli-contract-replay.md`](opencli-contract-replay.md)），发生在第 3 节
clone 能渲染之后，契约由构建阶段已冻结的产物派生而来。因为对象是仓库自有的
本地 fixture，该路径允许仓库 wrapper、CLI 与 schema；其结果只作诊断，不形成
trace coverage，也不构成任何门禁。

## 3. 构建本地 clone

复用 `src/websitebench/` 的认证、SQLite、邮件、验证和 Harbor 代码，在
`materials/<site>/clone/` 实现站点专属前端与业务语义。每站使用独立数据库、
数据目录、session、migration 和 reset seed。资源全部本地化，公开 UI 不泄漏
fixture、benchmark 或开发说明。

`websitebench-offline-clone verify` 的 `static` 与 `live` 分区诊断 scope、assets、
候选文件、路由与浏览器状态，输出 `clean`、`findings` 或 `incomplete`；它不保存
状态，也不作验收结论。`websitebench-workflow` 可诊断 automatic semantic
selection、visual calibration、full-stack candidate 和 rights disposition。
findings 可驱动 Agent 持续修复并重跑受影响检查。

走查路由/状态矩阵时同步记录 interaction ledger：clone URL、每个被激活控件的
selector、一条可见文本与一条原始标记证据、每次写操作背后的表单 action。
selector 只存在于这次走查，任何冻结的 scope 产物都不包含它。

完成上述构建输入后立即用 `websitebench-harbor derive-from-clone
--clone-manifest materials/<site>/clone.yaml` 从 `clone.yaml`、
`tools/frontend_samples.json` 与 `scope/*.json` 派生 Harbor interaction
contract 和 adapters。命令直接返回 `pending`；用 ledger 补齐 selector、逐条
清空 pending，必要时以 `--force` 重新生成，再对本地 clone 回放各 profile。
契约在这一步随 clone 一同产出，不留到第 5 节。`opencli` 不可用时记录
`opencli-unavailable` 并继续。

## 4. 自动校准

启动精确候选并记录 URL、process/container、candidate tree、seed、数据库与
迁移版本。独立 Verification Agent 使用
[`build.md`](../prompts/offline-clone/build.md)
对 matched source/clone 状态检查视觉、交互、响应式、键盘/触控、失败恢复和服务
端语义。Producer Agent 修复结构化 finding 并返回新证据；维护者根据 scope、
实现、覆盖率和诊断决定是否继续下一轮，直至达到交付目标或留下明确 blocker。

可选的 `websitebench-webcloning` normalize、select/import、exploration、replay、
diff 与 validate 工具量化行为差异。它们只产生绑定精确输入的诊断，不形成
corpus membership、发布门禁，也不授予版权或公网发布许可。

## 5. Harbor

使用 `websitebench-harbor validate/materialize` 生成隔离 bundle，并实际运行 NOP、
oracle、重复 oracle、visibility、network audit 与自动化浏览器矩阵。各机器检查
互不替代。最终检查 clone 的 v2 manifest 和当前 verification evidence。

interaction contract 不在这里编写——它在第 3 节随 clone 一同派生。这里只为
`<site-id>` 建立 `harbor/sites/<site-id>` 与 `harbor/instances/<site-id>` 这一组严格
一对一的 `init-site`/`init-instance` authoring 输入，再生成 bundle。站点的各个
journey 进入唯一 instance 的 hidden suite，而不是再创建 instance。选中的契约
profile 会逐字复制进 bundle，派生过程不生成 sidecar。

## 6. 公网部署

`deploy/generic-offline-clone/` 是描述符驱动的单站 Cloudflare Container 组件。
它复用任意现有 clone 源树与公共认证代码，生成隔离 container context 和
Wrangler 配置。默认是 dry run；真实外部部署必须显式传 `--yes`。部署成功不会
更改 Harbor、rights 或机器保真；技术状态由目标站点自己的 manifest 和当前
current evidence 决定。

历史 review records 与兼容 schema 保留为既有成果，不是活动 workflow。
