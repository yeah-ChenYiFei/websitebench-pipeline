# creativebug 离线克隆 — 未修完的问题

区别于 `scope/known-differences.json`：那里记的是**有意的偏差**（用户裁定或政策要求，
每条有测试守着）；这里记的是**尚未做到的事**。两者不许混用。

## 尚未执行的验证

> 本节 2026-08-30 校正过一次：此前写着「当前无任何相似度读数」「只有 40 条自动化测试」，
> 两句在写下时就已过期，与同目录的 README-RUN 互相矛盾。数字一律以实跑为准。

- **`verify --section live` 未跑过。** 只跑过 `static` 段。live 段要启动克隆并在浏览器里
  走检查点。
- **像素相似度已测量但未达标。** 2026-08-30 最终：21 条，纳入分母 16 条，
  **达标 10 条，中位 0.9372**。未达标 6 条已全部定性：2 条是取舍代价、
  2 条是量测配方差异、1 条参照帧拍错、1 条已修但差 0.003。明细见
  `scope/ACCEPTANCE-READINGS.md`。
  读数在 `tools/_visual.json`，明细见 `scope/ACCEPTANCE-READINGS.md`。
  失败项的性质分两类（个人数据不可比 / 克隆自制页），见本文末两节。
- **人工浏览器闭环未执行。** 自动化闭环已有（见下），但 AUTH-FLOW §7 要求的
  「人在浏览器里手工走一遍」仍未做。
- **交互审计报告仍缺。** `scope/interaction-ledger.summary.json`（明细见同目录 `.json.gz`） 已建（分母
  discovered/required = 166,817，仅 anonymous+desktop 单组合），
  但没有 `interaction-audit-report.json`——即有分母、无分子，
  §13「运行时 required 交互分母 = 通过数」仍无法评估。

## 台账未冻结

`purpose` / `routes` / `journeys` / `invariants` / `checkpoints` / `coverage` 均为
`status: draft`。§G3 要求台账内容在抓取完成后冻结，且每个数字都能从产物里重新数出来。
`coverage.json` 目前只有 1 个维度、`satisfied_items` 为空，与实际 1007 条路由不匹配。

## 覆盖缺口

- ~~`checkpoints.json` 只有 1 条~~ **已补至 26 条**，覆盖 9 条 journey、
  desktop/mobile 两视口、匿名与登录两态；viewports 已含 tablet 声明。
  仍缺：tablet 视口没有实际检查点；23 条 trace 里的失败态（必填为空、越权提示）
  与结账 review/confirmation 页尚未建点。
- **课时结构缺失。** 源站 `chapters-pane` 走 AJAX，静态 DOM 里没有课时列表，
  因此 `cb_class.unit_count` 全部为 1，进度状态机退化为"一节课等于整门课"。
  完成态与证书因此无法真实区分多课时课程。
- **`/api/outbox` 等调试接口未实现**，`test_outbox_never_exposes_challenge` 里对它们的
  断言因 404 而平凡通过——该测试对这几个路径**没有实际约束力**。

## 资产

口径：遍历 `tools/_assets.json`（11,035 条映射），检查映射名在
`clone/static/assets` 是否落盘。**按文件名或内容哈希直接比对
`incoming/cb-out/assets` 与 runtime 目录是错的**——两侧命名不同，
CSS 合入后还会被本地化改写。

2026-08-30 最终复核（服务器侧补抓 + 用户机器抓回一轮后）：
11,774 条映射中 **4 条缺文件，全部为源站侧不可得**，不再尝试。

- `category_lander_subcategory_holiday-and-party_quick-classes.jpg`（404）
- `category_lander_subcategory_needlework_holiday-and-party.jpg`（404）
- `category_lander_hero_knitting.jpg`（404）
- `profile/6285/.../1k8belihgkcb4dm3hmjt.jpg`——返回 200 但内容是品牌化 404
  HTML 页，合并阶段按规则拒收（拒得对）。

**本轮补回 2 条**

- `content/compressed/gallery-carousel-8813282b.css`（4,466 字节，服务器侧取回，
  此前从未被抓取器发现）
- `homepage_slides/original/623/0wroiu3kwmjqi2oface4.jpg`（133,528 字节，
  服务器侧被 WAF 挡三轮，由用户机器走 A1 浏览器路径抓回）

口径提醒：`fetch_missing.py` 原为 4 路并发，与口径 6「并发 1、真实间隔」不符，
已改为串行 + 1.4~2.6s 间隔。

登录态首页现存 1 个失败请求：`pimage/.../tutorial_thumbnails/original/2268`，
源站返回品牌化 404 页，该元素在页面上是 0×0 不可见，画面无缺口。

- **favicon 不在声明资产里**（见 known-differences），文件仍可服务。

## 已知实现薄弱处

- **`_deliver_mail` 的失败路径未测。** SMTP 不可达时是否正确 `finish_mail_claim`
  并保留可重试状态，没有测试覆盖。
- **`site_backend` 的支付适配器未接。** 结账目前直接写 `cb_order` 表，
  未经 `websitebench.site_backend.payments` 的 `local-sandbox` 适配器，
  与 `backend/model.json` 声明的 `payment-attempt` 实体不一致。
- **前端表单未接线。** `clone-runtime.js` 依赖 `data-cb-action` 属性驱动表单提交，
  但构建器尚未在源站表单上注入该属性，因此页面上的注册/登录表单目前**不会调用 API**。
  认证链路只在 API 层验证过，UI 层未接通。


## 2026-08-28 追加

- **表单接线刚落地，未经端到端验证。** 构建器现在把源站表单的 action
  （`/services/access/validate`、`/send_reset_password`、`/signup/save`）映射到克隆的
  `/api/*`，并把 `member[email]` 这类字段名归一。但**尚未在浏览器里点过一次**，
  40 条测试验的仍是 API 层。UI 层是否真的接通，要等浏览器闭环。
- **`test_outbox_never_exposes_challenge` 的部分断言无约束力。**
  它对 `/api/outbox`、`/api/debug/mail` 的检查因这两个端点返回 404 而平凡通过。
  这两个端点本就不该存在（SMTP 模式禁止回显 challenge），但"因为不存在所以通过"
  和"存在且不泄露"是两回事，测试目前不区分。
- **coverage 的 `satisfied_items` 全为空。** 5 个维度、23 条 required_items 已声明，
  但没有任何一条被标记为已满足——满足与否要由 live 段的实测结果回填，那一步还没跑。

## 2026-08-29 夜间收口后仍开着的

### 1. 边界页横向溢出 13px（桌面 1440）—— 成因已查明，未修
`/_clone/out-of-scope`：`documentElement.scrollWidth` = 1453，
但 **`body.scrollWidth` = 1440（内容本身干净）**。

排查过程（全部本地完成）：
- 无任何元素 `right > 1440`（已去掉宽度下限重查，仍为空）
- html / body 的 margin、padding 均为 0，overflow 均为 visible
- 真凶是伪元素：`.nav-expand-arrow::after`
  （`position:absolute; right:-12px; width:6px`），从父元素右缘探出 12px

来源：该箭头属于**抓取件里的页头外壳**（源站自身的装饰性 CSS），不是克隆生成的
恢复页内容。其他页面有同一个页头却未被判溢出——边界页主体区窄（720px），
布局不同，箭头恰好落在视口右缘。

**未修的理由**：忠实性无法在本地判定。源站没有"边界页"这个页面可供对照，
需要人在源站任一含该导航的页面上核对箭头是否同样越界。在此之前修改等于
猜测，可能制造源站没有的差异。

影响：边界页视觉相似度 0.8019（该页是克隆生成页，本就不与任何源站页面对应）。

### 2. 移动端三条溢出（去留待定）
`home.mobile` 422/414、`signup-entry.mobile` 416/414、
`subcategory-list.mobile` 422/414。用户已口头表示"我们不跑移动端"，但移动端
目前仍在冻结的范围契约里（26 个检查点中 5 个是 mobile，且参考帧已采集）。
**这是范围变更，需用户明确确认后才动契约。**

### 3. 五条个人数据检查点天然不可比
`gallery-mine` 0.5431、`recent` 0.5871、`library` 0.5943、`dashboard`、
`watchlist`：参考帧是采集者账号的真实个人数据，克隆里是新建试用账号。
衡量的是"谁的账号"，不是复刻质量。判定方式待用户裁定。


## 2026-08-30 第三轮（照独立审阅第二轮收口）

本轮把「点得动但没反应」这一整类补完了。四项修复各自带守护测试。

### 已修

1. **离线闭合被打破（P1）** —— `/rewards`、`/account/rewards` 的内联样式里有 22 处
   `url(&quot;https://cdn-widget-assets.yotpo.com/…&quot;)`。浏览器解析属性时把
   `&quot;` 还原后**真的发出 11 次外发请求**。
   成因是 HTML 实体转义：`build_pages.py` 的 `repl_css` 与三道离线守护的正则
   都只认裸引号，转义后整个漏过。
   修法：构建器正则接受实体引号；`test_offline.py` 读文件后先 `html.unescape`。
   已做反向验证——重新植入一处转义外链，守护会 FAIL。

2. **Bootstrap 控件全体失效（P1）** —— tab / collapse / dropdown 不写内联 onclick，
   `bootstrap.js` 按 §4.5 剔除后**不报错、只是没反应**，因此三套浏览器审计与
   118 条测试当时全绿。实测：531 个课程页上 Chapters / Materials / Gallery /
   Annotations / Transcript 六个页签一个都点不开。
   已在 `clone-runtime.js` 按出货件自身的 CSS 契约重新实现三种行为。

3. **15 个内联 handler 函数未定义（P1）** —— 34,238 个调用点、1009/1010 页，
   点一下抛 ReferenceError。已全部补上：`sel` `orderReviews` `openPanel`
   `topFunction` `scrollToDownloads` `expandReplies` `newAnnotation`
   `hideActivity` `likeComment` `clickReply` `clickEdit` `myFunction`
   `ga` `trackLearningJourney` `enableUsableNetAssistive`。

4. **`about:blank` 作中和替身（P2）** —— 它不是图片 URL，浏览器仍发起加载并以
   `ERR_UNKNOWN_URL_SCHEME` 失败：3,662 处、1,007 页，每页 2~3 条控制台报错，
   其中 767 处可见 `<img>` 显示成碎图（708 处是 Login with Amazon 按钮）。
   已统一换成 1×1 透明 GIF 的 `data:` URI，零请求。

5. **`<object data="…">` 未本地化** —— `/trial/create-account` 上的
   `whyjoin_hello.svg` 停在源站路径 `/ui/…`，实测 404。
   构建器的资产改写属性表漏了 `data`，已补。

### 本轮新增的守护

- `clone/tests/test_inline_handlers_resolve.py`（3 条）——
  钉住「每个内联 handler 函数都有定义」「data-toggle 控件有接线」
  「window.* 真的导出了」。三条均已做反向验证（破坏后会 FAIL）。
- `clone/tests/test_neutralization_and_session_only.py`（4 条）——
  钉住中和替身、会话内行为、埋点桩不发请求。

### 本轮仍未做

- 人工浏览器闭环、`verify --section live`、`interaction-audit-report.json`
  （见本文第一节）。
- 视觉相似度未因本轮改动重测——本轮改的是行为与外链，
  `about:blank` → 透明像素会让原先的碎图变成空白，**理论上视觉分数只会持平或变好，
  但没有实测，不得声称改善**。

## 2026-08-30 第四轮（照"能测出来就改"收口）

- **边界页 13px 横向溢出：已修。** 成因确认为 `.nav-expand-arrow::after`
  （CSS 开关法逐条排除得出）。**只在两个克隆自制页上收掉**——
  它们在源站没有对应物，不存在忠实性问题；源站派生页箭头保持原样，
  实测 `/`、`/classes`、课程页、讲师页溢出均为 0。
- **改投卡片自洽：已修。** 详见 `scope/ACCEPTANCE-READINGS.md`。
  新增 `tools/gen_class_thumbnails.py`（465/465 覆盖）与
  `clone/tests/test_substituted_cards_are_coherent.py`。
- **两个工具 bug：已修。** `compare_visual.py` 的 `similarity`/`score` 键名不一致
  （导致"排除项不进分母"从未跑通）、`shoot_candidate.py` 的 Mailpit 端口。

### 仍然开着

- ~~`boundary` / `not-found` 与参照帧设计不同，不可能达标~~ —— **该判断是错的**。
  按用户裁定改成统一取源站品牌化 404 抓取件后，两条都过了（0.9736 / 0.9743）。
  原先 0.80 的成因是手工拼页 + 漏了 `<html class="v2">`（443 条 CSS 规则失效）。
- 5 条个人数据检查点已声明排除，不进分母。
- 人工浏览器闭环、`verify --section live`、`interaction-audit-report.json` 仍未做。
- ~~四条未查明~~ **已查完**（见 scope/ACCEPTANCE-READINGS.md）：
  `gallery-community` 是克隆缺陷、已修（0.8606→0.9372）；
  `class-detail` / `static-about` 是**量测配方差异**（参照帧带 15px 经典滚动条，
  本机 headless 用 overlay 滚动条；对齐后 0.9646 / 0.9817，均过线）；
  `register-entry` 的**参照帧拍错了页面**（与 signup-entry 参照帧相似度 0.9993，
  拍的是同一个 `/trial/create-account`）。后两类要在你的机器上重拍参照帧才能收口，
  **没有为了过线去改度量或比较区域**。
