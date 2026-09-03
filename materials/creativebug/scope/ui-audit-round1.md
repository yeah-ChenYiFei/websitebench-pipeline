# UI 层自查（第一轮）：发现与修复

起因：接口层 65 条测试全绿，用户仍在几分钟内点出五个交互 bug。原因是那些测试
只证明"带正确载荷调接口能工作"，从不问"页面上的按钮点下去会不会调接口、带什么
载荷去调"。本轮补上后者。

工具：`tools/ui_audit.py`（匿名页面与表单）、`tools/ui_audit_auth.py`（登录态
旅程与 P0 主线 607）、`tools/ui_audit_rest.py`（其余 trace）。合计 71 项浏览器
断言，当前全部通过。

## 修复的真实缺陷

| # | 缺陷 | 影响 | 修复 |
|---|---|---|---|
| 1 | 服务器缺 SMTP 环境变量时静默进入 `LOCAL_ONLY`，注册链路一律 500 | 注册完全不可用，且 500 不暴露原因 | 新增 `clone/run.sh` 固化环境；`_deliver_mail` 在非 SMTP 模式下直接返回；启动打印 mail_mode；顶层异常改为服务端打 traceback |
| 2 | 邮件限流（会话内 60 秒冷却）被映射成通用 400 | 页头注册完再点页脚注册就"报错"，文案不说要等多久 | 单独映射为 429 + `Retry-After`，文案给出等待秒数 |
| 3 | 密码重置把限流也吞成"已发送" | 信没发出去却告诉用户已发送 | 限流按会话计、与邮箱无关，故回 429 不泄露账户存在性 |
| 4 | `/api/checkout/confirm` 无论 order_id 是否有效都回 200 confirmed | 订单停在 review 却已开 paid 订阅；可确认他人订单；可用请求体的 plan 顶替库里的 plan | 校验订单存在/归属/状态；plan 取库；重复确认回 409；记录并返回 `payment_profile=local-sandbox` |
| 5 | `/api/rating` 无范围校验 | `stars=99` 入库并参与课程评分聚合 | 限定 1..5、校验课程存在。（一并加的"必须已报名"前置随后撤回：源站无证据支持，且它改掉了已声明旅程的语义，并弄挂了 `test_rating_upsert_is_single_row`）|
| 6 | `/myclasses` 已报名课程从不渲染 | 接口有数据，页面空白 | 运行时新增 `hydrateMyClasses` |
| 7 | 搜索结果页从不渲染结果与空态 | 回车搜索落到通用目录页，既无结果也无提示 | 运行时新增 `hydrateSearch`，消费服务端注入的 `window.__cbSearch` |
| 8 | 两处 hydration 挂到 `#fragment-content` | 该容器是源站 offcanvas 面板里的空 div，尺寸为 0；内容进了 DOM 但一个字看不见 | 改用主内容流中可见的 `section#main`，并把断言从 `content()` 改成 `inner_text()` |

## 同时修掉的工具缺陷

- **PII 泄漏（阻断级）**：302 个出货页与数据库带着采集时的真实账号邮箱与内部
  id。根因是 scrub 只挂在 `finalize.sh` 上，而 build10 直接跑了 `build_pages.py`
  绕过去了。现已把 scrub 收进 `Builder.build` 管线末端，并补 `data-id` 规则、
  `test_no_pii.py` 钉住。数据库行已删除并 VACUUM。
- **mutation_check 中断不还原**：一次 `timeout` 击杀发生在注入与撤销之间，
  manifest 里留下 `bytes=1` 的假声明，此后所有 precheck 都报 ASSET_MISMATCH。
  现已用 `atexit` + SIGTERM/SIGINT 处理器登记撤销动作，并实测击杀后基线仍干净。

## 判定为"源站缺陷、忠实复现"的

见 `source-defects.md`：`/classes` 页一条被截断的图片 URL（原始抓取件中即如此），
以及 549 处指向未采集 highres 变体的 `og:image`（浏览器不请求，不影响渲染）。

## 审计自身的假阳性（已修正测法，不是站点问题）

- 搜索表单"无提交按钮"：它是原生 GET 表单，靠回车提交，实测可用。
- `/preferences`、`/account/orders`、`/account/subscription` 404：源站根本没有
  这三条路由，真实路由是 `/account/rewards`、`/account/plan_change`、
  `/account/cancel_subscription`，404 是正确答案。
- 多个表单连续提交撞限流：共享浏览器 context 造成的，真实用户每次访问是新会话；
  已改为每个表单独立 context。


## 第二轮：验证码没有页面落点（用户发现）

用户按提示注册后拿到了 Mailpit 里的六位码，却发现**页面上没有任何地方能输入它**。

- `register/start` 成功只贴一句 "Check that address for a six-digit code."，
  响应里的 `next: /trial/create-account?step=verify` 没有任何代码消费，
  该地址上也没有验证码表单。密码重置同样缺（`reset/complete` 需要码 + 新密码）。
- 违反 AUTH-FLOW §5「必须接通：六位码输入或邮件链接落点」，以及完成标准
  「关键流程不依赖手工修改 cookie 或浏览器控制台」。

**根因（也是我漏掉它的原因）**：三个浏览器审计脚本在这一步都直接
`fetch('/api/auth/register/verify')`。它们验的是接口，不是用户能不能用。
接口一直是好的，所以这个缺陷在 71 项审计里一路全绿。

**修复**：

- 运行时新增验证码面板（`renderChallenge`）：六位码输入框
  （`inputmode=numeric`、`autocomplete=one-time-code`、`maxlength=6`）、
  重置时附带新密码框、错误/过期文案、"换个邮箱 / 重发"按钮。
  邮箱与密码留在闭包里用于重发，不写进 DOM、不落 storage。
- `register/start` / `reset/start` 成功后就地把表单替换成该面板；
  直接打开 `?step=verify` 也渲染（`hydrateChallengeStep`）。
- 三个审计脚本改为 `verify_via_ui()`：在页面上填码、点按钮，不再走 `fetch`。
- 新增 `tests/test_verification_ui.py`（5 条）钉住落点存在、两条链路都有、
  错误文案可见、前端不读 worker token / SMTP 配置 / 数据库。

浏览器实测（全程点击，未碰控制台）：注册 → 错误码显示 "That code is not valid."
→ 正确码 → 跳 `/myclasses` 且会话已认证；重置 → 码 + 新密码 → 旧密码 401、
新密码 200。


### 第二轮补充：面板落在模态框里导致"看起来像空白页"

用户看到面板后反馈页面几乎是空的。诊断结果：页面内容并没有丢
（`section#main` 仍是 1877px、无遮罩），是两件事叠加：

1. `/trial/create-account` 上唯一接线到 `register/start` 的表单是登录模态框里的
   `#cb_login_modal_form`（y≈1715），高 689px。就地替换时把它藏掉，只剩一个空
   模态壳。
2. `code.input.focus()` 把视口滚到了 y=1444，正好停在那片空壳上。

**修复**：判断锚点表单是否在 `.cb-modal / .modal / .modal-dialog` 内；是则把面板
渲染成居中固定浮层 + 半透明背景（成功后一并移除背景），并用
`focus({preventScroll:true})` 不再劫持滚动；不在模态框内时才就地替换，并用
`scrollIntoView({block:"center"})` 温和对齐。已加回归测试。

### PII 会随人工测试反复进来

用户用真实邮箱在跑着的服务器上试注册，记录会落进
`local_auth_registration_flows` 与 `local_auth_mail_outbox` —— 交付库和本地库
是同一个文件。已做 `tools/purge_pii.py`（按 scrub-rules 的字面量清行 + VACUUM +
二进制层面复查），并作为 7b 步收进 `finalize.sh`，排在 verify 与测试之前。

人工测试期间 `test_no_pii` 报红是预期的，跑一次 purge 即恢复。
