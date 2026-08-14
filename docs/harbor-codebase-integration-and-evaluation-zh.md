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
与 Site 严格一对一并使用相同 ID。新骨架先生成空白 draft case/task/visual/CI/CD
文件；基于站点证据完成后，case manifest 必须恰好 200 项（T1=20、T2=165、
T3=15；T2 的 L1/L2/L3=35/50/80）。一个 journey 不再拆成另一个 instance。
不要把 reference 源码、隐藏 suite、终态 observations 或 reference raster 复制进
Agent 可见目录。

## 校验与 materialize

```bash
websitebench-harbor validate --instance harbor/instances/<site-id>
websitebench-harbor validate-corpus --corpus-root harbor
# draft 在此停止；只有 complete/sealed 的 200-case manifest 才继续
websitebench-harbor capture-reference \
  --instance harbor/instances/<site-id>
websitebench-harbor materialize \
  --instance harbor/instances/<site-id> \
  --out harbor-dist/<site-id>
```

空白 draft 校验退出 0，但明确标记 `scorable: false` 并列出缺失数量；capture、
materialize、calibrate 和 score 均拒绝 draft。校验会 fail closed 于非法路径、
visibility root 重叠、symlink/hard-link 风险、重复或缺失 case ID。Materializer
拒绝覆盖目标，并原子生成 bundle。
`bundle-manifest.json` 必须为每个文件记录 path、bytes 和 visibility。
`validate-corpus` 默认只校验当前 v2 的同 ID pair，并报告跳过的历史 manifest 数；
只有显式兼容审计才传 `--legacy-v1`。

## 信任边界

Candidate 只能看到 instruction、starter、公共合同和浏览器可访问的 reference。
可信 verifier、hidden fixture、reference 源码、required assertions、oracle solution
及校准分数必须保持不可见、不可写。候选由无参数 `compile.sh` 在私有离线沙箱中
编译成根目录 `executable`；运行时构建树只读，写入仅限独立 `DATA_DIR`。candidate
编译、启动、超时或断言失败保留在 200-case 分母；verifier/browser/sandbox
基础设施重试一次后仍失败则为 `INVALID_RUN`，不得发布 reward。

T2 journey 的 `J = F × V`，其中 Playwright 与 Browser Use 任一行为失败都令
`F=0`，无视觉 checkpoint 时 `V=1`，其余视觉采用 area-weighted RGB SSIM。
`Score20 = 4×R_L1 + 6×R_L2 + 10×R_L3`，reward 为 `Score20/20`；T1/T3 只进入
排序键。旧 deploy-v2 与 v1 分别只能经显式 `--legacy-deploy-v2`、`--legacy-v1`
兼容路径读取。

## 校准和人工交接

每个站点唯一 instance 的精确 bundle 依次运行：

1. NOP，确认空实现不能通过；
2. oracle；
3. reset 后重复 oracle，确认确定性；
4. visibility、build layer/cache/log 和 artifact transfer 审计；
5. network audit，确认 candidate 与 verifier 无未授权公网访问。

结果先写私有临时目录、fsync 并原子发布，最后写入 `receipt.json`；只有有效
receipt 才能生成 Harbor reward 文件。这些结果只证明 benchmark 工程性质。机器验证器仍需检查精确 runtime、来源
证据、已知差异和权利材料，另行决定保真接受与公开部署。任何助手或评分脚本都不能
擅自修改站点的 technically-verified 状态。
