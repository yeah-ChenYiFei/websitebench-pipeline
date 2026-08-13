# Harbor 在 Codebase 中的集成与测评

Harbor 把已经稳定的离线复刻候选封装为隔离、可重复评分的 benchmark。它不负责
来源采集、范围决定、视觉验收或发布批准。完整规范见
[`harbor-fullstack-benchmark.md`](harbor-fullstack-benchmark.md)；每个站点的
当前状态由其自身 manifest 和当前 evidence 决定。

新建任务默认使用纯确定性的 Harbor v2，详见
[`harbor-deterministic-v2.md`](harbor-deterministic-v2.md)。本文后续出现的 v1
维度和 exact node 仅用于历史兼容读取，不能满足 v2 的 reference capture、评分或发布流程。

## 进入条件

开始 Harbor authoring 前，机器验证器应已确认目标 scope，并取得：

- 身份绑定的 fullstack candidate 与可重复启动命令；
- deterministic reset、迁移与持久化证明；
- 本地资源闭包、浏览器 `remote=0` 和无公开调试文案；
- 当前机器证据和具名机器保真验证；
- 明确的 benchmark 使用权利边界。

缺少任何一项都可以继续做草稿 authoring，但不能把结果标为 benchmark-ready。

## 代码布局

| 路径 | 职责 |
| --- | --- |
| `src/websitebench/harbor/` | CLI、manifest 校验、scaffold、materializer |
| `harbor/sites/` | 可复用 site reference、public contract、verifier |
| `harbor/instances/` | 与 site 同 ID 的全站复刻 instruction、hidden suites、oracle |
| `websitebench/schemas/harbor-*.schema.json` | authoring contracts |
| `tests/harbor/` | 校验、materialization、scoring、隔离回归 |
| `harbor-dist/` | 生成 bundle，默认不提交 Git |

Site 保存稳定的 reference runtime、health、公共合同和可信 verifier。v2 Instance
与 Site 严格一对一并使用相同 ID，引用覆盖整个 scope 的隐藏 task、visual、CI/CD
suite、reference observations 和校准阈值。一个 journey 是 suite 中的一项 task，
不再为同一站点拆出另一个 instance。不要把
reference 源码、隐藏 suite、终态 observations 或 reference raster 复制进 Agent 可见目录。

## 校验与 materialize

```bash
websitebench-harbor validate --instance harbor/instances/<site-id>
websitebench-harbor validate-corpus --corpus-root harbor
websitebench-harbor capture-reference \
  --instance harbor/instances/<site-id>
websitebench-harbor materialize \
  --instance harbor/instances/<site-id> \
  --out harbor-dist/<site-id>
```

校验会 fail closed 于非法路径、visibility root 重叠、symlink/hard-link 风险、重复
节点、错误权重和不一致阈值。Materializer 拒绝覆盖目标，并原子生成 bundle。
`bundle-manifest.json` 必须为每个文件记录 path、bytes 和 visibility。
`validate-corpus` 默认只校验当前 v2 的同 ID pair，并报告跳过的历史 manifest 数；
只有显式兼容审计才传 `--legacy-v1`。

## 信任边界

Candidate 只能看到 instruction、starter、公共合同和浏览器可访问的 reference。
可信 verifier、hidden fixture、reference 源码、required assertions、oracle solution
及校准分数必须保持不可见、不可写。正式 verifier 在无公网环境使用低权限用户运行
candidate；candidate 启动失败是有效低分，基础设施失败则是 `INVALID_RUN`。

v2 唯一 reward 为等权任务完成率；visual RGB SSIM 和可信 CI/CD 通过率只并列报告，
不得影响 reward。旧 contract/API/UI/visual/journey/robustness 权重只属于显式 v1
兼容路径。

## 校准和人工交接

每个站点唯一 instance 的精确 bundle 依次运行：

1. NOP，确认空实现不能通过；
2. oracle；
3. reset 后重复 oracle，确认确定性；
4. visibility、build layer/cache/log 和 artifact transfer 审计；
5. network audit，确认 candidate 与 verifier 无未授权公网访问。

这些结果只证明 benchmark 工程性质。机器验证器仍需检查精确 runtime、来源
证据、已知差异和权利材料，另行决定保真接受与公开部署。任何助手或评分脚本都不能
擅自修改站点的 technically-verified 状态。
