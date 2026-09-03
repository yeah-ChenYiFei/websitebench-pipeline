# creativebug 离线复刻 — 独立审阅

**评审对象**：`materials/creativebug`
**评审基准**：`ULTIMATE-OFFLINE-CLONE-AI-COLLAB.md` §13 出口条件
**日期**：2026-08-30
**评审人**：独立评审 AI（无建造上下文）
**被审文档**：`REVIEW-vs-ULTIMATE.md`（建造者自评，2026-08-29）

> 自评第八节写明「§13 要求的无上下文独立审阅未做，本文不能替代」。
> 本文补上这一环。所有结论由本次实跑取得，不引用自评的读数作为证据。

---

## 一、结论

### 判定：`PARTIAL`（与自评一致，但理由不完全相同）

自评列的三条硬理由，**两条成立、一条需要修正**：

| 自评理由 | 独立复核 |
|---|---|
| 语义闭合不成立（链接改投） | ✅ **成立，且比自评描述的更严重**（见 F6） |
| 视觉合同未通过（10/21，中位 0.9332） | ✅ **完全属实，读数逐条复算一致** |
| 缺少运行时全控件审计 | ✅ **成立，且这个缺口正好掩盖了 F3** |

**新增两条自评未发现的 P1**（F3、F4），**同时撤销两条自评标为「未测」的失分项**（F11、F12 实测通过）。

### 一句话

**离线闭合与后端安全性是这个项目最扎实的部分，实测优于自评的保守表述；
但前端交互层有一个自评方法学看不见的系统性缺陷（F3），
且账本里存在一条「有测试守着却守错了东西」的假陈述（F2）。**

---

## 二、复核：自评说通过的，是否真的通过

| 自评主张 | 独立复核方法 | 结果 |
|---|---|---|
| 1009 页构建 | 遍历 `clone/frontend` | ✅ 1009 个 .html |
| 0 iframe | 全量正则扫描 | ✅ 0 |
| 0 外发请求 | 全量提取 `src/href/action/srcset/poster` 绝对 URL + CSS `url()`/`@import` | ✅ **站外 host 数 = 0**；`<a>` 共 502,774 处，站外目标 **0** |
| 视觉 10/21、中位 0.9332 | 重算 `tools/_visual.json` | ✅ 逐条一致，最低 0.5431 gallery-mine |
| 20 条台账 guarded_by 指向真实测试 | 解析每条 `file::func` 并核对函数存在 | ✅ 20/20 存在 —— **但见 F2** |
| 无 live key | 扫 `sk_live`/`pk_live`/AKIA/私钥 | ✅ 0 命中 |
| 密码不入明文库 | 读 schema + 二进制搜明文口令 | ✅ `scrypt-v1`，hash 64B / salt 16B，明文不存在 |
| cookie 安全 | 抓 Set-Cookie | ✅ `__Host-` + HttpOnly + Secure + SameSite=Lax |
| 防账户枚举 | 已存在/不存在邮箱各登录一次 | ✅ 文案与状态码完全一致（401） |
| `/api/reset` 回环限定 | 伪造 `Host: evil.example.com` | ✅ 403 |
| 七本账本缺失 | 逐个文件名查找 | ✅ 缺 6 本，属实 |
| 测试通过 | `python -m pytest tests -q` | ✅ **100 passed**（自评写 93，见 F8） |

**这一节的结论：自评没有虚报通过项。** 凡自评标 ✅ 的，独立复跑都站得住。

---

## 三、自评未发现的缺陷

### F1（P1）三条真实死链，且恰好是台账声称「可解析」的那三条

自评「D1/D2 闭合率 100%」的依据是 **40 页样本 1853 条链接**。
本次做了**全量**：1009 页共 502,774 处 `<a href>`，去重得 **984 个站内目标**，
逐个打到运行中的服务器：

```
200: 972    401: 9（受保护路由，正确）    404: 3
```

三条 404，全部来自 `clone/frontend/collections/index.html`：

```
/classseries/Autumn%20Holiday%20PG%202026
/classseries/Black%20History
/classseries/Unearth%20a%20Story
```

（同族第四条 `/classseries/iread%20summer%202026` 返回 200，所以不是编码问题。）

### F2（P1）台账假陈述，且守护测试守错了东西

`known-differences.json` → `source_unencoded_hrefs` 原文：

> 「Those routes were captured successfully and are reproduced;
> the clone percent-encodes the hrefs so they resolve.」

**实测 4 条里 3 条 404** —— 这句话不成立。

守护它的 `test_unencoded_hrefs_are_percent_encoded` 只断言
「前 200 页的 href 里不含空格」，**从不请求这些路由**。
所以测试恒绿，而它声称保证的事实是假的。

> 这一条推翻了自评表格里 `known-differences ✅ 全部 guarded_by 指向真实存在的测试 | 通过`
> 的**含义**：文件和函数确实存在（属实），但「存在」不等于「验证了该条陈述」。
> 建议对 20 条逐条重问一次：这个测试失败时，是否正好意味着该条陈述被违反？

### F3（P1）约 5.1 万个内联事件处理器全部抛 ReferenceError

`clone/static/clone-runtime.js` 是单个 IIFE（第 7 行 `(function () {`，
第 681 行 `})();`），且 `window.* =` 导出数为 **0**。
而抓取件保留了源站的内联 `onclick`/`onmouseover`，它们调用全局函数：

| 函数 | 调用点 | 覆盖页数 | 对应功能 |
|---|---|---|---|
| `liopen` | 12,036 | 1,003 | 侧边导航子菜单展开 |
| `sel` | 21,105 | 1,005 | 导航悬停高亮 |
| `hideActivity` | 8,613 | 319 | 活动流折叠 |
| `enlarge` | 4,744 | 630 | 图片放大 |
| `orderReviews` | 1,569 | 523 | 评论排序 |
| `enableUsableNetAssistive` | 1,006 | 1,006 | 无障碍开关 |
| `ga` | 786 | 720 | 源站 GA 埋点残留 |
| `openPanel` | 684 | 684 | 面板展开 |
| `thumbRate` | 330 | 68 | 评分拇指 |
| `topFunction` / `expandReplies` / `newAnnotation` / `scrollToDownloads` 等 | 约 420 | — | 回顶、展开回复、批注、跳下载 |

**合计约 51,300 个调用点，覆盖 1,006 / 1,009 页，无一个函数有定义。**

严重性说明（不夸大）：
- 这些**不产生外发请求**（`ga` 未定义即不发包），所以不影响「离线」轴；
- 多数 `liopen` 的 `<li>` 内含真实 `<a href>`，点文字仍能导航，属**降级**而非**完全失效**；
- 但 `enlarge`（图片放大）、`orderReviews`（评论排序）、`topFunction`（回顶）、
  `expandReplies`（展开回复）**没有非 JS 兜底**，是真正的惰性控件。

这正是自评第三节自己指出的后果：**没有 interaction ledger 就没有全控件分母**，
三次浏览器审计的 72 项断言是抽样，抽样正好漏掉了这一整类。
自评把「无惰性按钮」标为「前三项实测通过」，据此应改判。

### F4（P1）class_id 无参照完整性：假成功、500 泄漏、幽灵结业证书

`/api/{enroll,progress,watchlist}` 直接把请求体的 `class_id` 写库，不校验存在性：

| 输入 | 实际响应 | 应有响应 |
|---|---|---|
| `enroll` 缺 `class_id` | **200** `{"enrolled":true}`，实际因 `INSERT OR IGNORE` 静默丢弃，**一行没写** | 400 |
| `enroll` 用不存在的 class_id | **200** `{"enrolled":true}`，写入幽灵行 | 400 / 404 |
| `progress` 缺 `class_id` | **500** `{"error":"internal error","kind":"IntegrityError"}` | 400 |
| `watchlist` 缺 `class_id` | **500** 同上 | 400 |
| `progress` 用不存在的 class_id | **200** `{"completed":true,"certificate_available":true}` | 400 / 404 |

最后一行是最重的：**为一门不存在的课发放结业资格**。
随后 `/api/myclasses` 直接把脏行渲染出来：

```json
{"class_id":"no-such-class-xyz","title":null,"route":null,"unit_count":null}
```

即用户面板上出现一张标题为空、链接为空的卡片。

`cb_enrollment/cb_progress/cb_watchlist.class_id` 均无指向 `cb_class` 的外键，
是这一类问题的共同根因。

> 说明：本次探测写入的脏行与探测账号已全部清除，
> `PRAGMA integrity_check` = ok，`foreign_key_check` 为空。

### F5（P2）登录无限流

同一账号连续 12 次错误口令，**12 次全部 401，无锁定、无退避、无 429**。
自评「密码/验证码/session/cookie 安全 ✅ …限流 429」中的限流，
经核实**只覆盖发信**（同邮箱第 2 次 `register/start` 即 429，属实且正确）。

对照之下，**验证码尝试次数限制是做对了的**：5 次错误后流程作废，
此后即使提交正确的六位码也拒绝（实测确认）。登录路径缺的是同一层保护。

### F6（P2）语义偏离比自评描述的更宽

自评记为「40,434 条落到非对应页面」，`link-retargeting.md` 称替身选择
「同子类优先 → 同大类 → 全站」。独立测量（只取**标题型**锚文本：
≥3 词、≥12 字符、排除 "Watch Preview"/"…Image" 等通用文案，
与目标页 `<title>` 比对）：

```
标题型课程链接 13,692 条 → 不匹配 10,629 条（77.6%），覆盖 875 / 1009 页
```

且**大量跨大类**，并非文档描述的「同子类优先」的常见结果：

| 链接文字 | 实际落点 |
|---|---|
| Sew a Butterfly Wrap | Bliss Balls: Three Recipes For Snacking |
| Wire Linking Basics | Double Wedding Ring Quilt |
| Sew a Pair of Baby Bloomers | Jewelry Design: Working with Wooden Acc… |
| Quilt Block Oven Mitt | Flying Gosling Baby Quilt |

（该测量为下界估计：少量时长型锚文本如「1 hr 30 mins」被计入不匹配，属误判；
但上表这类跨品类实例本身已足以说明问题，不依赖计数精度。）

这不改变「用户已裁定保留」的事实，但**用户裁定时看到的描述
（同子类优先）与实际分布不符**，建议把真实分布回报给用户后再确认裁定。

### F7（P2）视觉合同的差距无法靠「个人数据不可比」全部解释

自评的推进方案第 2 条提出「裁定 5 条个人数据检查点」。逐条看 11 条失败项：

| 可用「参考帧是采集者账号数据」解释 | 不可用该理由解释 |
|---|---|
| gallery-mine 0.5431、recent 0.5871、library 0.5943、dashboard 0.905、watchlist 0.9332、gallery-community 0.8606 | **boundary 0.8019**、**not-found 0.8034**（克隆自制页，无参考帧个人数据问题）、register-entry 0.9264、class-detail 0.9294、static-about 0.9324 |

即：**即使 6 条个人数据项全部获准豁免，仍有 5 条低于 0.94**，
其中 boundary / not-found 是克隆自己写的页面。
`OPEN-DEFECTS.md` 已记录边界页 13px 溢出，与此吻合。

### F8（P3）交付文档读数已过期

| README-RUN.md 记载 | 实测（2026-08-30） |
|---|---|
| 工作树 93 passed | **100 passed** |
| clean-copy 89 passed / 4 skipped | 未复跑 |
| 启动输出 `routes=1007` | routes.json 与构建树均为 **1009** |

§13「三份文档与实际一致」按此不成立（差距不大，但确实不一致）。

### F9（P3）`/blog` 的行为与台账陈述相反

台账 `source_blog_returns_403` 称：「It is not reproduced as a page and
links route to the out-of-scope boundary.」
实际 `/blog` 是 `routes.json` 里的声明路由，**返回 HTTP 200**，
响应体是抓取到的 403 错误页（344 字节）。
即「以 200 承载一个 403 错误页」，与陈述不符。

### F10（P3）交付单元边界不清：`clone/` 不能独立启动

`clone/backend/site_backend_integration.py`:

```python
DEFAULT_RUNTIME_PATH = Path(__file__).resolve().parents[2] / "backend" / "runtime.json"
```

`parents[2]` 落在 `materials/creativebug/`，即 **`clone/` 之外**。
只 `cp -r clone` 到新路径启动会失败：

```
RuntimeContractError: runtime contract must be a regular file
```

不是缺陷（在原位与整目录拷贝下都正常，本次已验证），
但**交付单元必须是 `materials/creativebug/`，不能是 `clone/`**，README 应写明。

顺带更正一处方法学：README 用 `find … -type f -links +1` 为空来证明
「无 symlink/hardlink」。该命令只检测**硬链接**，检测不到符号链接。
正确的符号链接检查是 `find clone -type l`——本次实跑结果为 **0**，
所以结论碰巧正确，但**证明方法不成立**。

### F11（P3）隐私口径内部不一致

`/members/`、`/profile/` 因「slug 源自个人邮箱」被整体排除（判断正确）。
但课程页保留了源站的第三方评论区，其中含：
- 15 处源站自带掩码邮箱（`f...@comcast.net` 等，共 13 个不同值）；
- 真实用户头像图片资产；
- 一处 `alt="camille-foreman"`（真实姓名，位于「Review Replies (internal staff responses)」块）。

> 需澄清一个我最初的误判：这些 alt 槽位形如 `fatcomcastnet-56`，
> 看似比可见掩码泄露更多字符，实为 `f` + `at`（@ 写成 at）+ 域名扁平化，
> **与可见掩码等价，不构成额外泄露**。此处仅剩「排除 /members/ 却保留评论区」
> 这一口径不一致，严重性低，交由验收者裁定。

---

## 四、应从自评失分项中撤销的两条

自评把这两项标为 ❌/⚠️「未测」而失分。本次实测，**均通过**：

### F12 两进程重启持久化 —— 自评 ❌「未测」→ 实测 **通过**

隔离副本（端口 9188，整目录拷贝）上：注册 → 验证 → enroll → progress → watchlist，
`kill` 进程确认 healthz 断开，重新起进程：

- 旧 session cookie 仍 `authenticated: true`；
- `/api/myclasses` 返回重启前完全相同的记录；
- 用同一口令**重新登录**，取得新 session，数据一致。

### F13 并发 —— 自评「并发未测」→ 实测 **通过**

| 场景 | 结果 |
|---|---|
| 同一订单 12 路并发 `/api/checkout/confirm` | **200×1 + 409×11**，无重复确认、无 5xx |
| 同一课程 10 路并发 `/api/enroll` | 10×200，DB 内 **1 行** |
| 同一课程 10 路并发 `watchlist` 切换 | 10×200，终态一致 |

`app.py` 里那段 CAS 注释（记录了「先 SELECT 再 UPDATE 导致 8 并发中 3 次重复确认」
并改为条件更新 + rowcount 判据）**经实测确认修复有效**。这是本项目质量最高的一处后端实现。

---

## 五、修正后的 §13 判定

| 轴 | 自评 | 独立判定 | 变动原因 |
|---|---|---|---|
| 范围 | ⚠️ | ⚠️ | 不变 |
| 语义 | ❌ | ❌ | 不变，但偏离面更宽（F6）；另新增 3 条真实死链（F1） |
| 离线 | ✅ | ✅ | **全量复核后确认**，比自评的抽样依据更强 |
| 保真 | ❌ | ❌ | 不变；补充：豁免个人数据项后仍有 5 条不达标（F7） |
| 前端运行时 | ⚠️ | ❌ | **降级** —— F3 惰性控件成立 |
| 认证与后端 | ⚠️ | ✅（除 F5） | **升级** —— F12/F13 实测通过，仅余登录限流缺口 |
| 账本与交付工件 | ❌ | ❌ | 不变；补充 F2 假陈述 |

---

## 六、给验收者的建议

### 按「投入 / 风险消除」排序

1. **F4 参照完整性**（低成本、高收益）—— 三个端点各加一次 `cb_class` 存在性校验，
   非法输入回 400/404。消除幽灵结业证书与面板脏卡片。同时给三张表补外键。
2. **F2 台账假陈述**（低成本）—— 要么补齐那 3 个路由，要么把陈述改成事实
   （「4 条中 3 条未采集，链接指向 404」），并把守护测试改成**真的请求这些路由**。
   建议顺带对另外 19 条做同样的「测试失败 ⇔ 陈述被违反」自问。
3. **F5 登录限流**（低成本）—— 复用已有的发信限流设施即可。
4. **F3 惰性控件**（中等成本，但**这是标 COMPLETE 前绕不过去的**）——
   两条路线：(a) 构建期剥除源站内联 handler，改由 `clone-runtime.js` 用
   `addEventListener` 重新实现（与现有 modal/nav 接线方式一致）；
   (b) 只补 `enlarge`/`orderReviews`/`topFunction`/`expandReplies` 这几个无兜底的，
   其余作为已声明差异入台账。**无论走哪条，都需要先有 interaction ledger 提供分母**，
   否则下一轮审计仍会漏掉同类问题。
5. **F6 语义**——建议把真实分布（77.6% 标题型链接不匹配、跨大类实例）回报用户，
   在此基础上重新确认裁定。用户此前是在「同子类优先」的描述下拍板的。
6. **F1 死链**——3 条，随 F2 一并处理。
7. **F8/F9/F10 文档**（低成本）——刷新读数、更正 `/blog` 陈述、写明交付单元为
   `materials/creativebug/`、把符号链接检查改成 `find -type l`。

### 关于能否标 COMPLETE

**不能。** 自评的判断是对的，且本次新增的 F3、F4 使前端与后端各多一条 P1。
但同时应当承认：**这个站点的离线闭合与并发/持久化质量高于自评给出的印象**——
自评出于审慎把未测项一律标失分，实测下来那两项是通过的。

### 环境清理

本次审阅在隔离副本（端口 9188）上进行，已停止并删除临时目录。
探测期间写入交付库的脏行与测试账号已全部清除（`integrity_check` = ok）。
验收服务器 **9120 仍在运行**，未受影响；验收结束后仍需按自评第四节最后一行清理。

---

## 七、本文的自我限制

- 未做人工浏览器闭环，F3 的严重性分级基于 DOM 与 CSS 的静态推断
  （已区分「有 `<a href>` 兜底的降级」与「无兜底的惰性控件」），
  **建议实际点一次 `enlarge` 与 `orderReviews` 予以确认**。
- F6 的 10,629 是下界估计，计数含少量时长型锚文本误判；结论依据是跨品类实例，不依赖精确计数。
- 未复跑 clean-copy 测试（自评记录的 89 passed / 4 skipped 未经本次验证）。
- 未独立核验 `purge_pii` 的历史 302 页 PII 修复，仅核验了当前交付件的残留状态。
