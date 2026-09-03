# 源站自身的缺陷（clone 忠实复现，不修）

## 1. `/classes` 页有一个被截断的图片 URL

出货页 `frontend/classes/index.html` 中存在：

```
src="/pimage/dynamic/workshop-activity-card~storage/public/images/tutorial_thumbnails/original/2268"
```

该路径没有文件名与扩展名，请求必然 404。

**这不是构建器截断的。** 原始抓取件
`incoming/cb-out/pages/classes/index.html` 中该引用本身就是
`https://www.creativebug.com/pimage/.../original/2268`，全页仅此一条无扩展名，
其余 18 条同类引用都带 `/<id>/<name>.jpg`。源站在这个位置渲染出了一个不完整的
URL，真实站点上同样是坏图。

**处置**：忠实复现。浏览器审计中 `/classes`、`/classes/sewing` 等页出现的这条
404 属于预期，不计为 clone 缺陷。若后续有人"修好"它，反而制造了与源站的差异。

## 2. `og:image` 指向未采集的 highres 变体（549 处，532 个去重 URL）

`<meta property="og:image" content="/pimage/dynamic/highres~...">` 引用的是
高分辨率变体，与页面实际显示的缩略图是同一张图的不同尺寸。资产库中已有缩略图
变体，但没有 highres 变体。

浏览器不会请求 `og:image`，因此不影响渲染、离线闭包与视觉相似度；只有社交平台
抓取器会读它。已列入 `scope/missing-ui-assets.txt` 待下一轮采集补齐。在补齐之前
不做映射替换 —— 把 og:image 指向另一个尺寸的文件会制造出源站没有的差异。

## 3. 两个 CSS 引用的图片在源站已下线（404）

- `/ui/images/featureseeall.png`
- `/ui/images/price_999_account.png`

2026-08-29 采集时源站对这两个 URL 返回 **404**（其余 175 个同批资产均 200）。
它们仍被站内 CSS 的 `url()` 引用，属于源站自身的失效引用。

**处置**：不重试、不替代。克隆里这两处保持缺图，与源站现状一致。

## 2026-08-30：Slick `data-lazy` 图片全站不渲染（已修）

**现象**：全站 608 个页面、10,912 张 `<img>` 永远空白。登录态首页 15 张空白图里
有 12 张属于此类。

**成因**：源站轮播图的真实地址放在 Slick 的 `data-lazy` 属性里，由 Slick 在滑到
该帧时写进 `src`。§4.5 要求剥掉源站 JS，剥完之后没有任何代码做这件事。
资产本身早已抓取、本地化、落盘 —— 缺的只是"把 data-lazy 写进 src"这一步。

**为什么长期没被发现**：这些 `<img>` 的 `src` 是空字符串而不是坏地址，
浏览器不会发请求，因此**不产生 404**。只统计失败请求的检查一律看不到它；
必须统计 `naturalWidth === 0` 的图片才会暴露。

**修法**：`clone-runtime.js` 新增 `hydrateLazyImages()`，把 `data-lazy` 写进 `src`
并去掉 `slick-loading` 类。未用 IntersectionObserver：轮播容器 `overflow:hidden`，
非首帧被祖先裁掉判定为不相交，而翻页 JS 同样已被剥掉、用户永远翻不过去，
那些帧会永久空白。每页中位 19 张、最多 29 张，直接加载代价可接受。

**效果**：登录态首页可见图 82 → 94，空白 15 → 3（余下 3 张均为 0×0 不可见）。

## 4. 三张分类页图片在源站已下线（404）

- `/ui/images/categories/category_lander_hero_knitting.jpg` → `/classes/knitting` 的 400px 通栏 hero
- `/ui/images/categories/category_lander_subcategory_needlework_holiday-and-party.jpg`
- `/ui/images/categories/category_lander_subcategory_holiday-and-party_quick-classes.jpg`

`tools/_fetch_missing.jsonl` 三条均记 `"status": "404"`。同批 72 个
`category_lander_*` 资产其余全部 200 并已出货 —— 所以 `/classes/sewing`、
`/classes/quilting` 的 hero 正常而 `/classes/knitting` 右半边空白，
**这个差异来自源站，不是克隆的缺口**。

> 独立审阅第二轮曾据"同级页面有图"判定为克隆缺陷（N2），
> 复核采集记录后撤回：判据应当是采集时的源站响应，不是同级页面的观感。

**处置**：忠实复现，不补图、不换图。

**注意引用形态**：构建器对采集失败的资产仍然改写成了本地路径
（`/static/assets/0148c2642e-category_lander_hero_knitting.jpg`），
所以在克隆里这三条表现为**克隆自有命名空间下的 404**，而不是指向源站的 404。
两边都是坏图、行为一致，因此不改；但复核时不要据此判成"克隆自己的资产缺口"。
同型的还有 `/static/assets/24fd79dbf0-1k8belihgkcb4dm3hmjt.jpg`（源站返回
html-shell 软 404，归 `source_missing_images_return_soft_404`）。


## 5. `/site/ambassador` 有一个无扩展名的图片 URL

```
<img src="/ui/images/ambassador-monthly-pay">
```

与第 1 条同型：原始抓取件
`incoming/cb-out/pages/site/ambassador/index.html` 里就是这个形状，
没有文件名扩展。构建器的资产改写要求扩展名匹配，因此原样保留。

**处置**：忠实复现。浏览器审计中该 404 属预期。
