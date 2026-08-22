# Blinkist 离线复刻交付报告

Assignment `19`，`SITE_ID=blinkist`，任务表键 `WB019-T01..T23`。本报告只记录本地 clone、证据与诊断结果；不把机器 clean、Harbor reward、退出码或 Agent 自信解释为版权、发布或自动验收授权。

## 结论

建议作为**内部本地技术 draft 交付**，不建议公开部署、源站等价宣称或进入 Harbor 评分。P0 搜索/详情/收藏主链路、认证/本地邮件、密码恢复、本地 Premium sandbox 和 200 条可打开目录已经可运行；本轮又按已登录 Edge 只读采集对齐了 Daily 与 7 条 Masterclass 的源站 full slug、日期、主持人、时长和文案。严格视觉盲测、源站认证写入结果、真实邮件/支付、Harbor 200 case、资产再分发权利仍未完成或不可用。

## 功能优先级覆盖

| 优先级 | 覆盖 | 证据/限定 |
| --- | --- | --- |
| P0 | For You、Explore、搜索 Atomic Habits、详情、My Library/favorite、匿名到登录回跳 | `clone/tests/test_site.py`；本地 HTTP/SQLite；源站 favorite success 未执行，保持 unavailable |
| P0 | 注册、LOCAL_ONLY outbox、验证码验证、登录、登出、密码恢复 | 黑盒 7 tests；验证码仅 loopback debug endpoint，真实邮件不发送 |
| P1 | Premium annual local sandbox approved/declined/retryable | `SitePayments.create_intent/attempt/consume_approval` 与支付事件、幂等键、金额/币种/指纹；无真实付款 |
| P1 | 侧栏导航、Settings 子页与 localized aliases | `/app/daily`、`spaces`、`highlights`、`infographics`、`masterclasses`、`settings`、`settings/content`、`settings/email_optins`、`settings/external_services`、`settings/payment-history`、`en/nc/settings/invoices`、`app/check`、`help` 均有本地路由和状态流程；Masterclass 列表链接使用源站 full slug，旧短 slug 保留兼容解析 |
| P1 | 200 条可搜索、可打开、详情字段一致的本地书籍 | `len(BOOKS)==200`；每条有 author/category/description/rating/duration/narrator/key_ideas |
| P2/omit | 真实 audio playback、广告、analytics、第三方 widget、真实 checkout、外部邮件 | 未纳入离线运行时；不伪造源站不存在或未获证据的行为 |

正式 human trace 原样保持：`[821] Register on Blinkist with email reader2026@example.com, subscribe to the Premium annual plan, then search for Atomic Habits and add it to My Library (favorites)`。用户后来提供的其他邮箱未替换正式 trace，也未写入源站流程。

## 视觉、状态、角色与 viewport

- Source：匿名证据、已登录 Edge/CDP `127.0.0.1:9227` 的 authenticated read-only depth、desktop `1440x900` screenshots；观察到 `/en/app/for-you`、Explore、Library、Daily、Spaces、Highlights、Infographics、Settings 与 7 条 Masterclass full-slug 路由。非 GET 请求在辅助采集脚本中全部阻断。
- Candidate：Playwright Edge executable，desktop `1440x900`、tablet `1024x768`、mobile `390x844`，7 个页面族另加 forgot/reset，生成 21 张截图与 `capture-summary.json`。
- 状态：anonymous、local member、empty library、search results、no-results、detail、favorite、registration challenge、LOCAL_ONLY mail、authenticated、payment approved/declined/retryable、password recovery、Settings language/email toggle/payment empty、Connection check passed、404/auxiliary unavailable copy。
- 角色：anonymous、clone-local member、diagnostic operator。未读取或保存源站身份标识、密码、OTP、Cookie、Token、Authorization header 或 profile。
- 本轮又完成一轮可测视觉/响应式校准：侧栏图标与搜索提交按钮、For You 精选卡片文案、Settings 路由 active 状态、Masterclass 可点击左右控制，以及 390/768/900/1024px 下导航、筛选、Daily、Settings 的横向溢出修复。未参与实现的独立盲测尚未获得，不能声称“普通用户难以区分”。当前已知视觉残差：生成式 typographic covers、字体/图标、卡片密度、详情页部分 copy/spacing 与源站不同；对同一 finding 未继续第三轮无测量改善，登记为 known difference。

## Source 与 candidate 轨迹

- Source：`materials/blinkist/artifacts/trajectory/tr-001-source/`，仅脱敏事件 ledger；源站未执行注册、订阅、付款、邮件、收藏或登出。
- Auth source evidence：`materials/blinkist/source-auth-scratch/2026-08-22-auth-readonly-v2/`（完整 GET 结构/正文摘要/网络 host/截图）；`capture-report.json` 及 `route-observations-summary.json` 记录另一轮非 GET 阻断侦察及其不完整正文，不能替代 v2 完整 GET 证据。
- Candidate：`materials/blinkist/clone/browser-output/trajectory/tr-001-candidate/`，本地 Playwright 生成，13 actions、27 screenshots（3 viewport × 9 routes）并保留隐私策略。
- Diff：`materials/blinkist/artifacts/trajectory/candidate-diff.json`，diagnostic-only，similarity `0.125`、findings `28`。差异主要来自 source 轨迹的重复 library/For You 序列和 candidate 额外覆盖认证/订阅页面；该工具不评价像素、copy、网络闭包或业务语义。

## 资产闭包与运行时网络

- `materials/blinkist/source-assets/manifest.json` 为辅助证据；clone 运行时只挂载本地 CSS/JS，不请求 Blinkist 或第三方 origin。
- `websitebench-offline-clone verify --section static`：`diagnostic_status=clean`、`remote_references=0`、`secrets=0`，退出码 0；Edge Playwright loopback walk 13 routes，`remoteRequests=[]`。
- Edge Playwright viewport smoke check：390/768/900/1024/1440px 目标路由 `scrollWidth===viewportWidth`；移动主导航含 8 个入口、Settings 区含 2 个入口；For You Masterclass 两个箭头存在且点击后 `scrollLeft=281`。
- 封面为本地确定性 typographic placeholders，不宣称是 Blinkist 原始图片；商标、图片、字体、内容再分发权利为 `unknown`。

## Backend runtime 与隔离身份

- 权威 runtime：`materials/blinkist/backend/runtime.json`；`site_id=blinkist`，SQLite `materials/blinkist/data/blinkist.sqlite3`，offline-harbor profile 为 persistent + local-outbox + local-sandbox。
- session cookie：HTTPS/runtime 使用 `__Host-websitebench-blinkist-session`（Secure/HttpOnly/Host-only/SameSite=Lax/Path=/）；本地 HTTP 在显式 `WEBSITEBENCH_LOCAL_HTTP_COOKIE=1` 且 loopback 下使用独立 `websitebench-blinkist-session`，解决浏览器拒收 `__Host-` 非 HTTPS Cookie，正式 runtime 契约未改变。
- 邮件：LOCAL_ONLY outbox；`/api/local/outbox` 仅 loopback 且 debug fixture 开启时返回当前 session 的本地验证码，不发送真实邮件。
- 支付：Premium annual `9999 USD cents`，payment flow/attempt/event 与 subscription mutation 同一 SQLite 事务；只允许 `sandbox-approved|sandbox-declined|sandbox-retry`。
- 数据绑定：backend lifecycle 在数据库中绑定 `websitebench_site_binding=blinkist`；跨 actor favorite/library 由 server-side account ownership 隔离；重启后 SQLite 持久化。

## Harbor same-id site/instance 与 authoring dry-run

- Same-id site：`harbor/sites/blinkist/site.yaml`。
- Same-id instance：`harbor/instances/blinkist/instance.yaml`，OpenCLI profile `for-you` 已绑定，adapter contract check 通过。
- `websitebench-harbor validate --instance harbor/instances/blinkist`：退出码 0，`status=draft`、`scorable=false`、`reference_observations=pending`、`0/200` cases，missing `T1=20,T2=165,T3=15,L1=35,L2=50,L3=80`。这是按用户要求保留的 draft，不是目录数据数量。
- Harbor adapter replay：`for-you-8453.json`、`book-detail-8453.json` 均 `status=failed`，原因是当前环境 PATH 没有 `opencli` binary；不能描述为 replay 通过。

## 命令与退出码

| 命令 | Exit | 结果 |
| --- | ---: | --- |
| `python -m py_compile app.py test_site.py capture_clone.py` | 0 | 语法通过 |
| `PYTHONPATH=materials/blinkist/clone pytest -q materials/blinkist/clone/tests/test_site.py` | 0 | `23 passed`，1 个依赖弃用 warning |
| `node .tmp-node-playwright/verify_blinkist_local.mjs` | 0 | 本地 Edge/Playwright route walk 13 routes；本地注册（含条款）、验证码、email preference 持久化、connection check 通过，`remoteRequests=[]` |
| Edge Playwright viewport smoke check | 0 | 390/768/900/1024/1440px；无横向溢出，移动导航可达，Masterclass 箭头点击后滚动有效 |
| `websitebench-offline-clone verify --site materials/blinkist --section static --out .../static-verify-final.json` | 0 | clean、remote refs 0、secrets 0 |
| Playwright `capture_clone.py` | 0 | 3 viewports、7+2 auth routes、21 screenshots、candidate trajectory |
| `websitebench-browser-trajectory diff ...` | 0 | diagnostic compared；similarity 0.125，28 findings |
| `websitebench-harbor validate --instance harbor/instances/blinkist` | 0 | draft/non-scorable、0/200 |
| `websitebench-harbor run-opencli ...` | 0（artifact writer） | artifact status failed；opencli unavailable |
| `websitebench-offline-clone verify --site materials/blinkist --section live` | 1 | `diagnostic_status=incomplete`：诊断器隔离子进程读取 Windows-mounted runtime.json 报 Permission denied；Edge Playwright 手动 loopback 实测通过 |

## 修改路径

- Clone/runtime：`materials/blinkist/clone/app.py`（Daily 与 7 条 Masterclass full slug/metadata、兼容 alias）、`clone/static/site.css`、`clone/static/site.js`、`clone/backend/site_backend_integration.py`、`backend/runtime.json`、`backend/model.json`。
- Tests/tools：`materials/blinkist/clone/tests/test_site.py`、`materials/blinkist/tools/capture_clone.py`。
- Evidence/artifacts：`materials/blinkist/source-current/`、`source-assets/manifest.json`、`artifacts/static-verify-final.json`、`artifacts/live-verify.json`、`artifacts/trajectory/`、`clone/browser-output/`。
- Auth evidence：`materials/blinkist/source-auth-scratch/2026-08-22-auth-readonly-v2/` 及只读采集脚本/截图；不含 Cookie、Token、Authorization header 或密码。
- Harbor：`harbor/sites/blinkist/`、`harbor/instances/blinkist/`。

## Known differences、unavailable 证据与阻塞项

- Known differences：封面、图标/字体、真实源站图片与音频控件、部分认证 copy、推荐内容密度和页面垂直节奏；Daily 倒计时仍是本地确定性显示；Masterclass detail 中除已采集到正文的 Innovation Edge/Learn Like a Pro 外，其余源站 detail 正文证据不完整；独立盲测未安排，无法给出 PASS 数。
- Unavailable：源站注册/真实登录结果、Premium 真实 entitlement、真实邮件投递、真实付款、源站 favorite success/persistence、源站后端错误与成功 copy、原始资源再分发权利。
- Account deletion note：本地账户删除会清理站点内容/认证数据；`websitebench_payment_*` 保留为不可逆 payment audit ledger，owner 为本地不透明 account id，符合“删除个人数据但保留法定账务记录”的隔离策略，未伪造删除支付审计记录。
- Blockers：Harbor 当前没有可安全补齐的正式 200 case 内容；OpenCLI binary/Browser Bridge 不可用；live verifier 的 WSL Windows-mounted permission error；权益/商标/图片/字体/内容许可未提供。
- 文档状态：`scope/claims.jsonl`、`scope/coverage.json`、`scope/invariants.json` 与 `backend/model.json` 仍是 draft/planned scaffold；本报告不把它们升级为已证明的 benchmark contract，黑盒测试证据独立保存在 clone tests/artifacts 中。

## 交付建议

建议交付为内部 local technical draft，并保留 Harbor `draft/non-scorable`。不建议公开部署、真实账户/支付操作或版权再分发。理由是本地功能、状态、隔离身份、离线网络闭包和测试证据已具备，但 source-side mutation evidence、严格盲测、Harbor 200 case authoring、完整 live diagnostics 与 rights metadata 尚未满足。
