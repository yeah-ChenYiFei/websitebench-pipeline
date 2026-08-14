# 验收手册（人类视角）

本手册回答一个问题：**agent 交付的每个阶段产物，人怎么判断能不能收。**
所有机器命令的输出都是证据、不是决定；`clean` 只表示机器没发现问题。

约定：`<site>` 指 `materials/<site-id>`。金样本参照物：`materials/tripit`。

## 0. 通用检查（每次验收都做）

```bash
websitebench-offline-clone status --site <site>
websitebench-offline-clone verify --site <site>          # static + live 两段
```

- 报告 schema 为 `offline-clone.diagnostic-report.v1`，authority 恒为
  `diagnostic-only`。状态 `clean` / `findings` / `incomplete` 都需要人的判断。
- 抽查报告里的 findings：是真实差异，还是已在 known-differences 里诚实登记。

## 1. 范围冻结验收

看 `<site>/scope/`：

- [ ] 目的、P0/P1 journey、route/state 矩阵、语义不变量、non-goals 是否明确、
      可读、无含糊（对照 `materials/tripit/scope/`）。
- [ ] `checkpoints.json` 的 checkpoint × viewport 覆盖了声明的核心 journey。
- [ ] `verify.json` 里的路由别名 / 状态配方是否解释了匿名诊断到不了的路由。
- [ ] 范围之外的东西是否明确写进 non-goals，而不是默默缺失。

## 2. 源证据验收

看 `<site>/source-current/`、`<site>/source-assets/`：

- [ ] 每个 checkpoint 有对应的源捕获（截图/HTML/资产），带时间与环境记录。
- [ ] **红线**：随机抽查若干捕获文件，确认没有 cookie、authorization 头、
      会话令牌、真实用户数据。`grep -ri "set-cookie\|authorization" <site>/source-current/ | head` 应无敏感命中。
- [ ] 无法取得的面（如登录后页面）是否记录为 `unavailable` 而不是伪造。

## 3. Clone 构建验收

```bash
cd <site>/clone && python app.py           # 应能直接离线启动
python -m pytest <site>/clone/tests -q     # 站点自带测试全绿
```

- [ ] 浏览器手动走一遍 P0 journey：页面、跳转、表单行为与源站语义一致。
- [ ] `verify` 的 live 段通过或其 findings 已被诚实解释。
- [ ] 断网状态下无远程请求（诊断的网络闭包检查 + 抽查 DevTools Network）。
- [ ] 视觉对比：抽 2–3 个 checkpoint 与源截图并排比对，差异是否已登记。

## 4. 后端语义验收

- [ ] 若涉及账号/邮件/结算等能力：`<site>/backend/runtime.json` 由
      `websitebench-offline-clone backend scaffold` 生成，未被手写替代。
- [ ] `site_id` 唯一，数据库/卷身份独立，重置行为确定性（跑两次 reset 比对）。
- [ ] 支付只允许 `local-sandbox`（或通过机器检查的 `stripe-test`）；
      **任何 live key 出现即整体拒收**。

## 5. Harbor 契约验收

```bash
websitebench-harbor derive-from-clone --help   # 派生入口
websitebench-harbor run-opencli --help          # 本地回放（advisory）
websitebench-harbor validate \
  --instance harbor/instances/<site-id> \
  --corpus-root harbor
```

- [ ] `harbor/sites/<site-id>/site.yaml` 通过 schema 校验；id 与 materials 一致。
- [ ] 新 site/instance 是严格同 ID 的当前 v2 pair；`runtime.deployment_abi` 为
      `websitebench.harbor.compile-executable.v1`，formal browsers 恰为 Playwright
      与 Browser Use，健康端点为 `/__websitebench/health`。
- [ ] `interactions/opencli-interaction-contract.json` 的 `pending` 列表已清空
      或每项有解释。
- [ ] replay 结果只作参考——确认它**没有**被接进任何评分或合并条件。
- [ ] `reference/` 内容与 `<site>/clone/` 同源（抽查关键文件）。

## 6. Harbor instance 验收

`harbor/instances/tripit/` 只保留历史 v1 身份，不是新站模板。新 instance 必须由
当前 `init-instance` 生成 compile-executable v2 空白 draft。

- [ ] 每个站点恰好一个同 id instance；`instance.yaml` 通过
      `websitebench-harbor validate`。
- [ ] 新骨架的 case/task/visual/CI/CD 内容均为空；draft 校验退出 0，并明确输出
      `status: draft`、`scorable: false` 与缺失数量。draft 不得 capture、
      materialize、calibrate 或 score。
- [ ] 进入正式评测前，case manifest 恰好 200 项：T1=20、T2=165、T3=15；
      T2 中 L1=35、L2=50、L3=80。可信平台检查属于 verifier 基础设施，不占
      200 个 site case。
- [ ] candidate 交付入口是无参数可执行 `compile.sh`，私有离线编译后产生根目录
      `executable`；运行时只使用 `HOST`、`PORT`、`DATA_DIR`、`SEED`、`TZ`，
      保持前台、响应 SIGTERM，并返回精确健康 JSON `{"status":"ok"}`。
- [ ] 每个 T2 journey 有显式终态 observation，Playwright 与 Browser Use 独立运行
      均通过；视觉只由固定 Playwright 渲染并按区域面积加权 RGB SSIM。
- [ ] agent 可见材料（public/）不包含 reference 源码、verifier、隐藏 fixture、
      oracle 内容——抽查打包产物而不是只看目录。
- [ ] 校准证据（NOP 低分、oracle 高分、可重复性）是针对当前 bundle 的，
      不是历史结果；有效结果必须最后写入可验证 `receipt.json` 后才发布 reward。
      尚未跑校准时必须如实标注——**未校准的 instance 不得进入评测发布**。

## 7. 部署验收（公网演示站）

产出定义：每个站点一个 `deploy/generic-offline-clone/deployment.<site>.v2.json`
描述符 + 一个 `deploy-<site>-public.yml` dispatcher（只暴露 `deploy` 布尔），
统一走 `.github/workflows/public-demo-site.yml`。

**发布前（无需任何授权，本地即可验）：**

```bash
cd deploy/generic-offline-clone
npm ci && npm test
node scripts/prepare.mjs --config deployment.<site>.v2.json --check-only
node scripts/deploy.mjs  --config deployment.<site>.v2.json --dry-run
```

- [ ] 描述符六字段齐全（schema_version/source_dir/backend_runtime/
      deployment_profile/runtime/cloudflare），域名**不写在描述符里**（由
      `backend/runtime.json` 的 `site.public_origin` 派生）。
- [ ] dispatcher 的 push 触发只注册不部署；`deploy=false` 只做验证与 dry-run。

**发布（人显式授权 `deploy=true` 后才允许，前置条件是仓库配好
`CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`/`BASIC_AUTH_PASSWORD` 等
secrets）：**

- [ ] workflow 全绿，`<site>-deployment-evidence` 工件里的 build id 与本次
      commit 一致（健康检查绑定构建身份，不是裸 curl）。
- [ ] 线上行为符合门禁设计：匿名访问 `/` 返回 **401**（Basic-auth）；
      认证后响应带 `x-robots-tag: noindex`；`/__bench/` 认证后为 404；
      `/healthz` 返回 `ok: true` 且 `site_id` 正确。
      金样本在线参照：`https://tripit.website-bench.com`。
- [ ] 按 `prompts/offline-clone/references/08-deploy.md` Phase 12 在线复检
      P0/P1 journey 与区域视觉比对；失败时**显式回滚并复检**，不假设存在
      自动回滚。
- [ ] 发布决定本身遵循 `deploy/public-demo-release-authority.md`；机器
      `clean` 不构成发布授权。

## 仓库级回归（合并前）

```bash
ruff check src tests websitebench
python -m pytest tests/test_prompt_freshness.py -q   # prompt 与代码的绑定
python -m pytest tests/offline_clone tests/harbor tests/project -q
```

## 永不放行的情形

1. 任何凭据/会话/支付秘密进入仓库、日志、截图或证据 —— 无条件拒收并清除。
2. 用降低阈值、扩大 mask、删测试的方式把指标"修"绿。
3. 把 `inferred` / `unavailable` 记成直接证据。
4. 把机器 `clean` 当成版权、再分发或部署授权。
