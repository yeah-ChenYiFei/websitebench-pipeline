# creativebug 离线复刻 — 独立审阅 第二轮

**评审对象**：`materials/creativebug`（当前工作树）
**评审人**：独立评审 AI（无建造上下文）
**上一轮**：`INDEPENDENT-REVIEW-2026-08-30.md`（F1–F13）
**方法**：所有结论由本轮实跑取得；对上一轮每条结论重新取证，不沿用旧读数。

---

## 零、必须先说的：树在审阅期间被改过

第一轮的读数取自一份 **8-29 快照**（`app.py` 40,832 字节）。
本轮开始时同一路径上的树已是 **8-30 快照**（`app.py` 46,829 字节，
`clone-runtime.js` 28,268 → 43,284 字节）。

按 mtime 排出的时间线，建造方是**照着第一轮报告逐条改的**：

| 时间 | 产物 | 对应 |
|---|---|---|
| 03:19 | `INDEPENDENT-REVIEW-2026-08-30.md`（第一轮报告落盘） | — |
| 03:23 | **新建** `scope/interaction-ledger.summary.json`（明细见同目录 `.json.gz`） | F3 的前置（缺分母） |
| 03:26 | **新建** `clone/tests/test_referential_integrity.py` | F4 |
| 04:42 | `known-differences.json`、`link-retargeting.md` | F2、F6 |
| 04:46 | **新建** `clone/tests/test_signin_rate_limit.py` | F5 |
| 11:18 | `clone/app.py` | F1 / F4 / F5 |
| 13:39 | `test_known_differences.py`（守护测试重写） | F2 |
| 14:25 | `clone/static/clone-runtime.js` | F3（部分） |
| 16:27 | **新建** `clone/tests/test_offline_closure.py` | 建造方自查 |
| 16:28–16:43 | `OPEN-DEFECTS.md`、`README-RUN.md`、`checkpoints.json` 等 | 文档 |

**因此第一轮的 F1/F2/F4/F5 不是误报**——它们准确描述了当时那棵树，
现已修复。本轮对每条重新验证并给出当前状态。

---

## 一、结论

### 判定：`PARTIAL`（未变），但失分项已经换了一批

**上一轮四条 P1 中三条已修**（F1、F2、F4、F5），
**但离线轴本轮首次被判不通过**——而它此前是自评与我都标 ✅ 的那一条。

| 轴 | 第一轮 | 本轮 | 变动 |
|---|---|---|---|
| 范围 | ⚠️ | ⚠️ | — |
| 语义 | ❌ | ❌ | 用户裁定保留，实测 75.0% 不匹配 |
| **离线** | **✅** | **❌** | **N1：22 处可抓取外部引用，浏览器实测 11 次外发请求** |
| 保真 | ❌ | ❌ | 10/21，中位 0.9329；另加 N2 缺图 |
| 前端运行时 | ❌ | ⚠️ | F3 部分修复（3/18 函数），**已由浏览器点击实证** |
| 认证与后端 | ✅（除 F5） | ✅ | F4、F5 均已修并有测试守护 |
| 账本与交付工件 | ❌ | ❌ | 新增 interaction-ledger；仍缺 6 本 + 审计报告 |

---

## 二、第一轮 F1–F13 的当前状态

| # | findings | 当前 | 本轮证据 |
|---|---|---|---|
| F1 | 3 条死链 | ✅ **已修** | 全量 984 个去重站内目标重跑：`200×975 / 401×9 / 其他 0`；新 `cp -r` 实例同样 4/4 返回 200 |
| F2 | 台账假陈述 + 守护测试守错 | ✅ **已修** | 陈述改写并写明根因（服务器未 unquote）；守护换成 `test_unencoded_space_routes_actually_resolve`（**真的请求这些路由**） |
| F3 | 约 5.1 万惰性内联 handler | ⚠️ **部分修** | 见下 §三 |
| F4 | class_id 无参照完整性 | ✅ **已修** | 缺参 → `400 class_id is required`；不存在 → `404 That class does not exist`；`test_referential_integrity.py` 9 项通过 |
| F5 | 登录无限流 | ✅ **已修** | 同账号连错 12 次 → `401×5 + 429×7` |
| F6 | 语义偏离 | ⛔ 用户裁定保留 | 重测：标题型链接 12,419 条，不匹配 **9,316（75.0%）**，覆盖 **843/1010** 页 |
| F7 | 视觉缺口不能全归因个人数据 | ❌ 未变 | 10/21，中位 0.9329；`not-found` 0.8031、`boundary` 0.8315 仍是克隆自制页 |
| F8 | 文档读数过期 | ⚠️ 部分 | README 已更到 109，**实测 118**；且 OPEN-DEFECTS 与 README 互相矛盾（N8） |
| F9 | `/blog` 以 200 承载 403 页 | ❌ 未变 | 仍 `200`，344 字节 |
| F10 | 交付单元 / symlink 检查方法 | — | 未复测 |
| F11 | 隐私口径不一致 | — | 未复测 |
| F12 | 两进程重启持久化 | ✅ 通过 | 第一轮已实证，本轮未复跑 |
| F13 | 并发 | ✅ 通过 | 第一轮已实证，本轮未复跑 |

---

## 三、F3 复测：从静态推断升级为浏览器实证

第一轮我标注「严重性基于 DOM/CSS 静态推断，建议实际点一次」。**本轮点了。**

`clone-runtime.js` 现有 3 个 `window.*` 导出。真实 Chromium 中派发 click：

| 控件 | DOM 变化 | 控制台 | 判定 |
|---|---|---|---|
| `enlarge`（图片放大） | +426 字节 | 无 | ✅ **已修复，真的能用** |
| `liopen`（侧栏子菜单） | +62 字节 | 无 | ✅ **已修复** |
| `orderReviews`（评论排序） | 0 | `orderReviews is not defined` | ❌ **仍是死控件** |
| `openPanel`（面板展开） | 0 | `openPanel is not defined` | ❌ **仍是死控件** |
| `enableUsableNetAssistive`（无障碍开关） | 0 | `enableUsableNetAssistive is not defined` | ❌ **仍是死控件** |

当前统计（1010 页）：

- 已定义 3 个：`liopen` 12,048 / `enlarge` 4,744 / `thumbRate` 330 = **17,122 个调用点已救活**
- **仍未定义 15 个 = 34,238 个调用点（66.7%），覆盖 1,009 / 1,010 页**

仍死的里面，用户可感知且**无非-JS 兜底**的：

| 函数 | 调用点 | 页数 | 功能 |
|---|---|---|---|
| `orderReviews` | 1,569 | 523 | 评论排序 |
| `openPanel` | 684 | 684 | 面板展开 |
| `enableUsableNetAssistive` | 1,007 | 1,007 | **无障碍开关（全站）** |
| `topFunction` | 129 | 129 | 回到顶部 |
| `newAnnotation` | 74 | 74 | 批注 |
| `expandReplies` | 57 | 15 | 展开回复 |
| `scrollToDownloads` | 9 | 9 | 跳到下载区 |

`sel`(21,126) 与 `hideActivity`(8,640) 数量最大但属悬停高亮/折叠，观感降级为主。
`ga`(786) 是源站埋点残留，未定义即不发包，**不影响离线轴**。

---

## 四、本轮新发现

### N1（P1）离线闭合被打破 —— 浏览器实测 11 次外发请求

**这是本轮最重要的一条**，因为离线是此前唯一被双方都判 ✅ 的轴。

`/rewards` 与 `/account/rewards` 两页的内联样式里有 **22 处**：

```html
style="background-image: url(&quot;https://cdn-widget-assets.yotpo.com/static_assets/…&quot;);"
```

浏览器解析属性时会把 `&quot;` 还原成 `"`，于是真的去抓。Chromium 实测：

```
加载 /rewards → OFF-ORIGIN 请求 11 次，全部指向 cdn-widget-assets.yotpo.com
```

全站扫描（1010 html + 58 css，先 `html.unescape` 再找**可抓取上下文**）：
**可抓取的站外引用恰好 22 处，全部是这一个主机、这两个页面，其余为 0。**

> 其余 13 个站外域名均**不产生请求**，不算违规：`schema.org`(microdata itemtype)、
> `w3.org`(SVG xmlns)、`ogp.me`(RDFa prefix)、`craftpip.github.io`/`github.com`
> (CSS 许可证注释)、`amzn.to`/`aboutads.info` 等（**href 已改投边界页，URL 只是可见文字**——这条做得对）。

**三道离线守护为什么全部漏掉它**：

| 守护 | 漏掉的原因 |
|---|---|
| `test_offline.py::test_no_third_party_host_in_built_pages` | ①按 32 个主机的**白名单**比对，而白名单里只有 `cdn-loyalty.yotpo.com`、`cdn-swell-assets.yotpo.com`，**没有 `cdn-widget-assets.yotpo.com`**；②不做 `html.unescape` |
| `test_offline_closure.py::test_shipped_css_has_no_external_references` | 只扫 `static/assets/*.css` **文件**，不扫 HTML 内联 `style` |
| `test_offline_closure.py::test_shipped_pages_have_no_external_stylesheets_or_scripts` | 只看 `<link rel=stylesheet>` 与 `<script src>` |

实证该正则的盲点：

```
FETCH 正则在原始 HTML 上匹配 yotpo： 0 处
先 html.unescape() 之后再匹配：     11 处
```

**修法（一行）**：把读文件处改成 `html.unescape(p.read_text(...))`，
并把白名单比对改成「不在 IN_SCOPE 即失败」的黑名单式判定——
白名单天然无法发现**没被登记过**的第三方主机。

### N2（P1）4 个资源引用了克隆自己的 `/static/assets/` 命名空间却没出货

不属于台账 `source_missing_images_return_soft_404`（那条讲的是**源站**缺图），
这 4 个是构建期把引用改写成了本地哈希路径、但文件既不在磁盘也不在 manifest：

| 资源 | 页面 | 影响 |
|---|---|---|
| `0148c2642e-category_lander_hero_knitting.jpg` | `/classes/knitting` | **400px 高的整条 hero 横幅空白** |
| `5ccbd74fa1-…needlework_holiday-and-party.jpg` | `/classes/needlework` | 子分类卡片图缺失 |
| `d71dfb08ac-…holiday-and-party_quick-classes.` | `/classes/holiday-and-party` | 同上 |
| `24fd79dbf0-1k8belihgkcb4dm3hmjt.jpg` | 2 个课程页 | 图片缺失 |

截图比对已确认：`/classes/knitting` 右半边整片空白，
而同级 `/classes/sewing`、`/classes/quilting` 的 hero 图正常——**证明是缺口不是设计**。

### N3（P2）全站资源闭合：87 个 404，508 处引用

11,237 个去重本地资源引用逐个 HEAD：`200×11,148 / 404×87 / 401×2`。

按类型：57 个头像、19 个图样缩略图、5 个课程缩略图、1 个活动图、4 个上面的 N2、3 其他。
最高频的一条 `…workshop-activity-card~storage/…/tutorial_thumbnails/original/…` 出现 **320 次**。

台账 `source_missing_images_return_soft_404` 覆盖了其中大部分（源站本就没有），
措辞是「a small number of image URLs」——**87 个 / 508 处，建议把实际数字写进台账**，
并把 N2 那 4 个单独拆出来（它们不是源站缺图）。

### N4（P2）2,702 个 `<img src="about:blank">`，每页都报错

覆盖 1,007 页。其中：

- **1,935 个是隐藏的追踪像素**（`batBeacon…`，`width=0 height=0 display:none`）——
  中和掉是**对的**，只是控制台每页留 2–3 条 `ERR_UNKNOWN_URL_SCHEME`；
- **767 个是可见的**，其中 **708 个是 "Login with Amazon" 按钮图，覆盖 687 页**——
  台账 `third_party_oauth_excluded` 说「renders the provider buttons」，
  但按钮的**图是空的**，与「渲染了」有出入；
- 另有 ~11 张真实内容缩略图（MLK Day / Women's History Month / Black History 等）空白。

另有 960 个 `<ximg src="about:blank">`——改了标签名，浏览器不会去抓，**这个处理是对的**。
建议统一：要么都改 `ximg`，要么把 `src` 换成 1×1 透明 data URI，消掉全站控制台报错。

### N5（P2）交互账本已建，但审计报告仍缺

`scope/interaction-ledger.summary.json`（明细见同目录 `.json.gz`） **已新建**，且 `note` 字段诚实写明
「actor=anonymous、viewport=desktop 单一组合；coverage 不得按本文件宣称全站 100%」——**这个自我限制写得好**。

分母现在是明确的：`routes 1009 / discovered 166,817 / required 166,817`。

但 **`interaction-audit-report.json` 仍不存在**，所以 §13
「运行时 required 交互分母 = 通过数」依然无法评估——只是从「没有分母」
变成了「有分母、没有分子」。另：该文件 **146 MB**，作为交付件偏大，建议压缩或分片。

十本账本现状：**已有 2**（interaction-ledger、known-differences），
**仍缺 8**（scope-contract、route-inventory、provenance-ledger、boundary-ledger、
capabilities、coverage-report、delivery-manifest、interaction-audit-report）。

### N6（P3）出货库里有一行幽灵数据

```
cb_enrollment: class_id='no-such-class-xyz', created_at='2026-08-30 03:24:39'
```

`no-such-class-xyz` 正是第一轮报告里的探针字符串，时间戳落在
`test_referential_integrity.py` 写盘（03:26:20）前两分钟——是**手工调试时打到交付库**留下的。

已验证**测试套件本身是干净的**：`conftest.py` 用 `tempfile.mkdtemp()` +
`WEBSITEBENCH_SITE_BACKEND_DATABASE` 隔离；单跑该测试前后幽灵行数均为 1，不增长。

> 我没有删它——它是建造方的产物，删掉会毁掉验收证据。交由验收者处置。
> （我自己第一轮探测写入的行已在第一轮末尾清干净，本轮探测全部在 `/tmp` 副本内进行。）

### N7（P3）路由计数三个数字对不上

`healthz` 报 **1010**，磁盘 html **1010**，`routes.json` **1009**。

### N8（P3）OPEN-DEFECTS.md 与 README-RUN.md 自相矛盾

同一棵树里，`OPEN-DEFECTS.md`（16:28 写）仍称：

> 「当前无任何相似度读数，**不能声称达标**」「目前只有 40 条自动化测试」「只在工作树跑过（40 passed）」

而 9 分钟后写的 `README-RUN.md`（16:37）称 109 passed，
`tools/_visual.json` 里有 **21 条**相似度读数，本轮实测 **118 passed**。
`scope/ACCEPTANCE-READINGS.md` 仍停在 8-29 的「93 passed」且写着
「离线闭包…0 外发请求」——该句已被 N1 证伪。

§13「三份文档与实际一致」不成立。

---

## 五、本轮复核确认仍然成立的（不用再动）

| 项 | 本轮方法 | 结果 |
|---|---|---|
| 站内链接闭合 | 984 个去重目标全量 HTTP | **0 死链** |
| 站外链接 | 502,774 处 `<a href>` | **站外目标 0** |
| 可抓取站外引用 | 1068 个 html+css，先 unescape | **仅 N1 的 22 处** |
| 参照完整性 | 缺参/不存在 class_id 五种输入 | 全部 400/404 |
| 登录限流 | 同账号连错 12 次 | 401×5 + 429×7 |
| 验证码锁定 | 5 次错码后提交**正确**码 | 仍拒绝（正确） |
| 测试套件 | `pytest tests -q` | **118 passed** |
| 测试隔离 | 跑测试前后查交付库 | 不污染 |
| 台账守护 | 20 条 `guarded_by` 逐条解析 | 全部指向真实函数 |
| 交付库完整性 | `PRAGMA integrity_check` | ok |

---

## 六、修复建议（按投入/收益）

1. **N1 离线闭合**（一行改动，P1）——`html.unescape` + 白名单改黑名单。
   **这条不修不能标 COMPLETE**，因为它推翻的是唯一一条曾被判通过的硬轴。
2. **N2 四个缺图**（低成本，P1）——补采或在台账里单列；`/classes/knitting` 的空白 hero 是首屏可见缺陷。
3. **N8 / F8 文档一致性**（低成本）——OPEN-DEFECTS 与 README 打架；ACCEPTANCE-READINGS 的「0 外发请求」已被证伪，必须改。
4. **F3 剩余 15 个死函数**（中等成本，P1）——分母已经有了（166,817）。
   优先补 `orderReviews`、`openPanel`、`enableUsableNetAssistive`、`topFunction`、`expandReplies`（均无兜底）。
5. **N5 interaction-audit-report**（工作量最大）——分子。另建议给 146MB 账本瘦身。
6. **N4 about:blank**（低成本）——换 1×1 data URI，消掉全站控制台报错；顺带修 "Login with Amazon" 空图。
7. **N3 台账措辞**、**N6 幽灵行**、**N7 路由计数**、**F9 `/blog`**（各自低成本收尾）。

---

## 七、给验收者的一句话

**建造方对第一轮报告的响应是扎实的**：四条 P1 修了三条半，
新增的三个测试文件和 interaction-ledger 都直指根因，
且 ledger 的 `note` 主动写明自己的覆盖边界——这是好工程习惯。

**但本轮把此前唯一"干净"的轴打掉了**：离线闭合有真实外发请求，
且三道守护因为白名单与 HTML 转义两个盲点全部漏检。
在 N1 修复并复验之前，仍应判 `PARTIAL`。

---

## 八、本轮的自我限制

- F10（交付单元/symlink 检查法）、F11（隐私口径）**未复测**。
- F12（重启持久化）、F13（并发）沿用第一轮实证，**本轮未复跑**。
- N1 的浏览器实证只跑了 `/rewards`；`/account/rewards` 需登录态，
  仅经静态确认含同样 11 处引用，**未在浏览器里实测**。
- F6 的 9,316 仍是**近似**（已排除时长型与通用文案，但锚文本判定本身是启发式）；
  结论依据是跨品类实例，不依赖精确计数。
- clean-copy（`cp -r` 新路径）**未复跑测试**；README 自己也注明新增的 20 条未在新路径跑过。
- 视觉参照帧的可比性问题（F7）本轮未推进，仍需人裁定。
