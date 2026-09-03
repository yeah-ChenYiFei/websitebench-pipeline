# creativebug 离线克隆 — agent handoff

- Site ID: `creativebug`　Source: https://www.creativebug.com/（apex 301 → www，规范主机是 www）
- 工作区: `/home/user/alive/creativebug-clone/`（全部产出在此）
- 只读引用: 引擎仓库 `/home/user/alive/aspca-pet-insurance-site/`；方法论 `/home/user/qutianlin/*.md`
- **不碰**: `/home/user/qutianlin/**` 的任何站点目录与 smtp 实例、`/alive/coolors-clone/`、`/alive/angi-local/`、`/alive/*-runtime-data/`
- 端口段: **9120–9129**　Mailpit: **127.0.0.1:1025 (SMTP) / 8025 (UI)** —— 按 AUTH-FLOW「本地 SMTP」统一口径，不再自建实例
- 环境: `source /home/user/alive/env.sh`
- 当前阶段: **G0 —— 走 A1 人工建会话路径**（见 `recon/G0-BLOCKER.md` 与 `tools/cb_capture.py`）

## 口径（用户 2026-08-28 裁定）

1. 流程按 `/home/user/qutianlin/FAST-CLONE.md`；有争议处按引擎仓库
   （`AGENTS.md` / `CLAUDE.md` / `prompts/offline-clone/`）。
2. **robots.txt 的 Disallow 路径在本任务授权取证范围内**（`/login`、`/account/`、
   `/api/`、`/search/results`、`/trial/create-account` 等）。
   ※ 这是**任务范围**授权，不是站方授权，也不解除 WAF 质询这个技术阻断。
3. **源站写操作按默认边界**：可登录/登出/报名免费或试用课/收藏；
   **不购买、不绑真卡、不改密码与邮箱、不删已有数据、不向源站发评论**。
   付费流在源站只走到 order review 之前停手，confirmation 由克隆侧自实现。
4. 账号状态：**新注册、free trial**（用户报告：登录后落点与首页近似，未见 dashboard——
   待 recon 证据判定是个性化主页还是 trial 未激活）。
   **凭据不在服务器上**：取证走 A1，登录由人在本机浏览器手动完成，服务器永不持有该账号密码。
   `run/creds.env` 已于 2026-08-28 shred 删除，全工作区字节流扫描 0 命中。
5. 交付口径同 coolors：**不做 Harbor、不做公网部署**，支付只用 `local-sandbox`。
   交付物 = 能跑的 `materials/creativebug/clone/` + 台账 + 三件套
   （`README-RUN.md` / `RUN-LOG.md` / `OPEN-DEFECTS.md`），**不打包**。

## 范围（来自用户给的 23 条 human trace，全站口径，未经用户同意不得收缩）

公开发现（入口→主导航→art-courses 区 / 分类浏览 / 分类页 / 搜索+6 类筛选 / 无结果态）·
课程详情（syllabus、instructor、prerequisites、reviews、pricing、enrollment options / 免费预览 / 课程材料）·
认证面（登录入口、注册入口、找回密码——源站侧只验结构不提交，克隆侧要真跑通）·
建号与登录（learner 账号 + profile/onboarding / dashboard / 已选课程）·
订阅付费（free trial / free-audit 与 paid track / 支付信息 → order review → confirmation）·
播放与进度（lesson 播放、unit 间导航、quiz/assignment + 反馈、续播、收藏、进度与完成态）·
账户与收尾（证书/完成、评分评论、学习偏好、account history 最新项带 status/detail/edit/cancel + 返回集合）·
失败态与边界（必填为空或登出态 → 行内校验或权限提示 / help-support-contact 不泄私有数据 / 深链 404 保留主导航）·
**P0 主线 task 607**：公开入口 → 注册 free trial → 浏览 Drawing & Illustration → 选 beginner 课 → 看第一课

## 口径增补（用户 2026-08-28 第二轮裁定）

6. **不换站**（Creativebug 是指定目标）。取证走 A1：用户本机浏览器 + 本人订阅账号，
   服务器不持凭据、不发起抓取。并发 1、真实间隔、遇质询退避不加码。
7. **不取视频内容**：不下载 `.m3u8` / `.mpd` / `.mp4` / `.ts` 分片、视频 CDN、字幕轨。
   播放器页的 DOM/CSS/poster/缩略图照取（布局要对），克隆侧播放器是尺寸一致的占位组件。
   记 `known-differences.json`: `video_content_not_reproduced`，配测试守着。
8. **截断收边用边界页，不用 404**（FAST-CLONE §5.2(b)）。
   404 必须继续只表示"路由不存在"——trace 里「品牌化 not-found 保留主导航」那条检查点依赖这个语义，
   若"未克隆内容"也回 404，两种情况就分不清了。
   边界页记 `known-differences.json` 并配测试。

9. **N = 12**（用户 2026-08-28 裁定）：每个子分类只克隆前 12 门课的详情页。
   截断收边用 §5.2(b) 边界页：列表页**所有卡片照渲染**（保 0.94 相似度），
   前 12 张链真详情页，其余链边界页。记 `known-differences.json`:
   `class_detail_truncated_at_12_per_subcategory`，配测试守着。
   被截断的**只有种子目录数据**——见口径 10。
10. **功能必须实现完整**（用户明确要求）。截断不适用于行为：
   认证全套（注册→Mailpit 六位码→验证→登录→登出→忘记密码，AUTH-FLOW §1 九条）、
   订阅状态机（trial / 付费档 / 取消）、`local-sandbox` 支付至 order review + confirmation、
   报名、观看进度、续播、收藏 watchlist、完成态、证书、评分评论、学习偏好、
   服务端授权不变量（登出态访问 /myclasses 必须真挡）。
   **课少，但每门课该有的行为都真实存在。**

## 实测站点事实（2026-08-28 G1 探针，15/15 OK）

| 项 | 读数 |
|---|---|
| 渲染 | 服务端渲染，登录态页正文 1181–3015 词，非 SPA 空壳 |
| 路由权威 | **无 sitemap**（超时 / 404）。靠首页出链 + 站内爬 |
| 列表结构 | `/classes` hub → `/classes/<cat>` hub(10) → `/classes/<cat>/<sub>` **真列表**(115) |
| **详情路由** | **`/classseries/single/<slug>`** |
| 分页 | **无**。单个 `workshop-collection-list` 块服务端一次渲染完（garment-sewing 72 项） |
| 列表容量样本 | garment-sewing 69 门课 / ceramics 16 门课（差异大，重叠率待 126 页实测） |
| 软 404 | `/zzzz-*` 返回 **HTTP 200** + 品牌化 404 正文（1171 词）。克隆侧拟回真 404，记 `source_soft_404_returns_200` |
| 第三方 | `lantern.roeye.com` 追踪像素、swell 组件 —— 构建期必须全剔 |
| 全站样板链接 | 160 条（导航+页脚），量列表项时必须先减掉 |

## robots.txt 记录（事实，非阻断）

站方 robots 对 GPTBot / ClaudeBot / PerplexityBot / CCBot / Google-Extended / ByteSpider /
Cohere-ai / FacebookBot 全站 `Disallow: /`；另按路径 Disallow `/login`、`/account/`、`/api/`、
`/search/results`、`/trial/create-account`、`/promos/`、`/se/`、`/af/`、`/ajax/modal`、`/services/`、`/lib/`。
用户已就任务范围授权（口径 2），取证机制为本人浏览器 + 本人账号，非爬虫 UA 抓取。
`Sitemap:` 声明的 `/sitemap.xml` 实测超时，`/sitemap_index.xml` 返回 404（响应体是首页 HTML，`<loc>` 数 0）
—— **无 sitemap 路由权威**，路由清单只能靠首页出链 + 站内有限深度爬。

## 原阻断项（已按 A1 化解）

AWS WAF bot-control challenge：curl 与 headless Chromium 均被挡；sitemap 全部 202/0 字节；
首页出链 0 → §5.4 页面总数算式写不出 → G0 通过条件第 5 条不满足。
出路三选一（**待用户裁定**）：人工驱动取证 / 站方授权与 IP 放行 / 换目标站。
不构建质询绕过（指纹伪装、stealth、代理轮换、质询求解器）。

## 与阻断项无关、可先行的

- `tools/precheck.py`（逐字复刻引擎 `assets.py:172 inspect_asset` 与 `:271 verify_asset_closure`）
- ~~`/alive/smtp/` 我们自己的 Mailpit（9125/9126）~~ **2026-08-30 更正**：AUTH-FLOW
  「本地 SMTP」与 §9 统一启动示例把 `127.0.0.1:1025` / UI `8025` 定为所有克隆的共用口径，
  自建实例属于接口偏离。已改用文档口径；只作为 SMTP 客户端投递，不修改该目录任何文件。
- `local_clone_auth` + `site_backend` 接线骨架（认证/订阅/进度后端，不依赖源站取证）
