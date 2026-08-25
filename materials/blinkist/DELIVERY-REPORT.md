# Blinkist 离线复刻修复交付报告

日期：2026-08-25

站点：`blinkist`

范围：Blinkist clone、站点合约与证据、站点 CI，以及必要的公共静态诊断覆盖。

## 完成结论

人工 review 指出的首页侧边导航、视觉残差、底部入口、注册、登录与付款逻辑均已修复并完成本地回归。

- Blinkist 测试：`110 passed`，包含四宽度 Playwright 浏览器回归。
- 公共诊断器测试：`20 passed`。
- 完整诊断：`diagnostic_status=clean`，static/live 完整执行，findings 0。
- Live：`55/55` checkpoints，session checkpoints `36/36`，外部请求拦截 finding 0。
- Static：扫描 29 个候选/后端声明文件，remote reference 0、secret 0。
- 有效视觉契约：My Library desktop `0.9740 >= 0.7`；阈值未降低，未扩大 mask。
- For You 的保留 raster 与声明 viewport 不在已证明的同一坐标系，因此不再报告误导性的量化分数；页面 checkpoint、结构证据和浏览器回归均保留。
- 浏览器回归覆盖 `390 / 768 / 1024 / 1440` 四个宽度、15 个核心路由，共 `60/60`。
- 未部署、未 merge、未访问真实邮件或付款，也未修改 Harbor 配置。

Harbor failures were intentionally excluded from this remediation scope and do not affect this round’s completion decision.

## Review finding 修复映射

| Finding | 修复结果 | 回归证据 |
| --- | --- | --- |
| 首页侧边导航差异过大 | 首页使用默认关闭的左侧抽屉，包含登录、Business 与 8 个分类；关闭状态使用 `inert` 移出 Tab 顺序，打开后限制 Tab/Shift+Tab，Escape 关闭并恢复 opener focus。会员侧栏保留完整本地入口和 active 状态。 | drawer keyboard test；四宽度 browser matrix |
| 底部入口只有跳转、缺少逻辑 | 公共 footer 的 Pricing、Business、Contact、Terms、Privacy 均落到同源且具有对应语义的页面。会员 footer 的 Cancel Subscription 现在有确认页、POST 状态转换，并在取消后撤销本地 Premium 访问。Sitemap、Privacy、Accessibility、Terms 均展示匹配内容。 | footer 语义测试；subscription cancel 状态测试；live checkpoints |
| 视觉残差与坐标证据 | 重建会员侧栏、For You 模块、Library、详情、Settings、auth 与 Premium 布局；动态颜色改用有限 CSS class。My Library 保留有效同坐标 visual contract。For You 的未知缩放 raster 降级为结构证据，未删除 checkpoint 或降低阈值。 | My Library `0.9740 >= 0.7`；60/60 browser routes；claims/provenance |
| 注册、登录、恢复不完整 | member 路由由服务端统一保护；匿名 direct URL 303 到 `/login`；多层编码反斜杠、scheme、NUL 与 protocol-relative `next` 均拒绝；登录安全回跳、登出与 stale session 均覆盖。注册对 duplicate、active flow、rate limit 和 authenticated-session 冲突统一返回 opaque `303 /verify`。 | auth、registration、recovery 和 stale-session 回归 |
| OTP 明文 HTTP 暴露 | `/api/local/outbox` 固定 404；验证码仅可由显式 test mode 的进程内 session/purpose seam 获取；SQLite 只保存 salt/hash。 | privacy 与 backend lifecycle tests |
| 付款流程不完整 | Premium annual 使用明确标记的本地 sandbox，覆盖 approved、declined、retryable、重复/并发、伪造金额、stale fingerprint、foreign owner 与 invalid scenario；不接收卡数据，不连接 provider。新增真实本地取消状态。 | payment lifecycle、receipt、cancel、actor isolation tests |
| CSP 与安全边界 | 保持 `default-src/connect-src/form-action 'self'`，不加入 `unsafe-inline`；增加 `frame-ancestors 'none'` 与 `base-uri 'none'`。带 foreign Origin 或 cross-site fetch metadata 的 POST 返回 403。 | CSP/foreign-Origin tests；browser runtime errors 0 |
| GET 产生持久化副作用 | preview/read/check/settings GET 不再创建 history、check 或 preference 记录；显式 progress/check POST 才写入。重复 refresh 不改变三类表。 | GET refresh/no-mutation test |
| Tablet overflow、touch、heading | 761–900 breakpoint 允许 rail/topic/cover shrink 与 wrap；没有用全局 `overflow-x:hidden` 掩盖问题。核心路由在 390、768、1024、1440 均检查 scrollWidth；每页一个 H1；移动交互目标按实际 label hit-area 检查 44px。 | `test_browser_regression.py`，60/60 |
| Account delete 语义矛盾 | 页面明确说明删除会结束本地订阅，并删除 profile、library、learning state、settings 和 local order；不可变 payment audit 只可能保留 opaque transaction id，不含 email/card data。 | account delete/order cleanup test |
| actor isolation 声明缺证据 | 新增 A/B 综合测试，覆盖 subscription、order、progress、preference 和 foreign order lookup，并保留 favorite/space/highlight 隔离测试。 | actor-isolation tests |

## 隐私与来源证据

- 当前候选树无非保留域个人邮箱；扫描输出只显示文件、行号、类别和脱敏上下文。
- `tools/privacy_scan.py` 扫描 email、Cookie/Set-Cookie、Authorization/Bearer、token/key/secret、password、private key、provider live key、Cloudflare API token、OTP、支付卡数据、国际电话、邮寄地址和 tracking URL query identifier。
- 每一类均有合成正向 fixture，并断言 scanner render 不回显 payload。
- 五个敏感或不可作为验收证据的文件已从候选树移除，并以权限 600 保留在私有 review quarantine：两张可能包含身份信息的 Settings raster、Cloudflare challenge DOM，以及含第三方 tracking identifiers 且 provenance 不完整的 Explore DOM/summary。
- 候选树中的 `unavailable.json` 说明移除原因、capture metadata、retention 与 mutation boundary。
- 20 个保留 EA2 JSON 已补 source origin、exact URL、viewport/raster、locale、timezone、role/auth、browser、provenance、retention 与 mutation boundary。
- Git 历史未重写。历史若仍含敏感值，必须另行制定 remediation plan 并取得维护者授权；本 PR 使用从 `main` 创建的干净快照，不继承受污染的功能分支历史。

最终 privacy scan exit 0、无 finding；所有身份均为 `example.invalid` 合成数据。

## Scope 与后端状态

| 合约 | 最终状态 |
| --- | --- |
| `scope/routes.json` | 28 routes，frozen |
| `scope/checkpoints.json` | 55 checkpoints，3 diagnostic viewports，frozen |
| `scope/journeys.json` | 7 journeys，frozen |
| `scope/coverage.json` | 7 dimensions，frozen |
| `scope/invariants.json` | 10 invariants，frozen |
| `scope/claims.jsonl` | 6 claims |
| `scope/verify.json` | aliases、state recipes、member session 与 isolated boot |
| `backend/model.json` | verified，6 capabilities |

诊断合约保持 desktop `1440×900`、tablet `768×1024`、mobile `390×844`；额外 `1024×768` 宽度由可重复 Playwright regression 覆盖。

后端回归覆盖 reset、restart persistence、migration replay、backup/restore、foreign-site fail closed、registration/favorite/payment concurrency、delete/write race、OTP stale/foreign/locked/consumed、known/unknown recovery、payment state machine、session revocation和 actor/site isolation。所有 SQLite 位于 review cache。

## Static / live diagnostics

最终报告：`/home/user/xuehw/.cache/review/blinkist/diagnostic-pr-I3rvK68Z/full.json`

Static：

- `execution.complete=true`
- `files_scanned=29`
- `remote_references=0`
- `secrets=0`
- findings 0

Live：

- `execution.complete=true`
- `checkpoints=55`、`page_loads=55`
- `session_checkpoints=36`、`session_checkpoints_unvisited=0`
- `sessions_requested=1`、`sessions_opened=1`、`sessions_failed=0`
- `blocked_external_references=0`
- `visual_contracts=1`
- findings 0
- observation：Library desktop similarity `0.9740 >= 0.7`

公共诊断修复位于本仓库的 `src/websitebench/offline_clone/diagnostics.py` 与 `tests/offline_clone/test_diagnostics.py`。它扫描候选代码、backend model、runtime 与 asset manifest 的敏感信息；remote runtime 检测覆盖 HTML attributes、JSON URL fields、`fetch`、WebSocket/EventSource/Worker、Requests、HTTPX 与 urllib 调用，同时不把 asset provenance URL 错报为运行时加载。

`.github/workflows/tests-blinkist.yml` 直接运行统一 Blinkist diagnostics 并上传 advisory report，不调用 Harbor preflight；diagnostic finding/incomplete 仍保持 maintainer-judgment-required，不被伪装成 merge gate。

## 可重复浏览器回归

`clone/tests/test_browser_regression.py` 在独立 loopback 进程和 review-cache SQLite 上运行 15 个核心路由 × 4 个宽度：`1440×900`、`1024×768`、`768×1024`、`390×844`。

每行验证 HTTP/final render、title、单 H1、横向 overflow、console error、pageerror、failed request 与 external request；390px 额外检查交互 hit area。抽屉测试另验证 inert、Tab/Shift+Tab trap、Escape 与 focus restore。最终 `60/60` 路由检查包含在 `110 passed` 中。

此前保留的手工 browser report 为 `/home/user/xuehw/.cache/review/blinkist/browser-final2-wNzxebvc/browser-matrix.json`；当前提交以仓库内可重跑的四宽度测试为准。

## 最终命令结果

| 命令 | Exit | 结果 |
| --- | ---: | --- |
| Blinkist clone pytest（isolated DB） | 0 | `110 passed` |
| `tests/offline_clone/test_diagnostics.py` | 0 | `20 passed` |
| privacy scan | 0 | 无 finding |
| backend model validator `--require-verified` | 0 | verified，6 capabilities |
| full offline-clone verify | 0 | clean，static/live complete，55/55 |
| `ruff check ...` | 0 | passed |
| `git diff --check` | 0 | passed |

运行时产物全部位于 `/home/user/xuehw/.cache/review/blinkist/`，未写入站点 data 目录。

## 修改边界

- Clone：`clone/app.py`、`clone/static/site.css`、`clone/static/site.js`。
- Tests：`test_site.py`、`test_remediation.py`、`test_backend_lifecycle.py`、`test_privacy.py`、`test_browser_regression.py`。
- Privacy：`tools/privacy_scan.py`。
- Scope/backend：routes、checkpoints、journeys、coverage、invariants、claims、purpose、derived brief、verify driver、backend model。
- Evidence：EA2 provenance 更新、EA1 raster provenance、sensitive/challenge unavailable records；五个敏感/无效证据文件从候选树移除并隔离。
- Common：diagnostics scanner 与 tests。
- CI：`.github/workflows/tests-blinkist.yml`。

未修改 Harbor 或其他站点。

## Unavailable / non-goal

- 源站注册、登录、恢复、favorite 与 Premium entitlement mutation：未获授权，未执行。
- 真实邮件、真实支付、卡数据和 provider callback：禁止；clone 仅有 local sandbox。
- Cloudflare challenge：仅作 failure provenance，不作为 authenticated page evidence。
- Settings 敏感 rasters、Explore tracking DOM/summary：已隔离并标记 unavailable。
- For You raster 的 device scale/crop mapping：不可证明，因此不作量化 visual acceptance claim。
- Onboarding 与原始商标/图片/字体再分发授权：不在本轮范围。

最终提交从 `origin/main` 建立干净分支，只包含上述 Blinkist、公共 diagnostics tests 与站点 CI；不包含功能分支的 113 个无关 commits，也不重写历史。
