# creativebug 离线克隆 — 怎么跑

## 前置

- Python 3.11+
- 本地 Mailpit（认证邮件）：SMTP `127.0.0.1:1025`，UI `http://127.0.0.1:8025`（AUTH-FLOW §「本地 SMTP」统一口径）

## 起站

```bash
cd clone
export PORT=9120
export WEBSITEBENCH_SMTP_HOST=127.0.0.1
export WEBSITEBENCH_SMTP_PORT=1025
export WEBSITEBENCH_SMTP_FROM=no-reply@creativebug.clone.test
python app.py
```

启动输出形如 `creativebug clone on http://127.0.0.1:9120  routes=1007  classes=465`。
健康检查：`curl http://127.0.0.1:9120/healthz`。

不设 SMTP 三个变量也能起，但认证会退到 `LOCAL_ONLY` 模式、不投递真实邮件。

## 数据

- 业务库：`data/creativebug.sqlite3`（可用 `WEBSITEBENCH_SITE_BACKEND_DATABASE` 覆盖）
- 目录种子：`clone/backend/catalog-seed.json`，465 门课，启动时 UPSERT（可重复执行）
- 重置账户侧状态：`clone/backend/seed.py::reset_account_state`

## 跑测试

```bash
cd clone && python -m pytest tests -q
```

需要 Mailpit 在跑；测试会自建临时数据目录与端口，不污染工作树。

## 主要路由

| 面 | 路由 |
|---|---|
| 目录 | `/classes`、`/classes/<分类>`、`/classes/<分类>/<子分类>` |
| 课程详情 | `/classseries/single/<slug>` |
| 讲师 | `/instructors/<name>` |
| 认证 | `/trial/create-account`、`/subscribe/create-account`、`/forgot-password` |
| 登录态 | `/myclasses`、`/myclasses/{library,recent,watchlist}`、`/account/profile`、`/preferences` |
| 边界 | `/_clone/out-of-scope`（克隆未覆盖）、`/_clone/not-found`（路由不存在，返回 404）|

## API

`/api/session`、`/api/search`、`/api/myclasses`、`/api/enroll`、`/api/progress`、
`/api/watchlist`、`/api/checkout`、`/api/checkout/confirm`、`/api/rating`、
`/api/auth/{register/start,register/verify,signin,signout,reset/start,reset/complete}`

支付一律 `local-sandbox`；不接受任何 live key。

## 测试读数（§11 要求：工作树与全新 `cp -r` 路径各一次）

| 环境 | 结果 | 日期 |
|---|---|---|
| 工作树 `materials/creativebug/clone` | **129 passed, 0 failed** | 2026-08-30 |
| 全新路径 `cp -r` 出来的副本 | **121 passed, 4 skipped, 0 failed** | 2026-08-30 |

两处条数一致（128；副本读数为 125 条时所测，新增 3 条守护未在副本复跑）。副本里的 4 条 skip 是环境相关的（构建器不在交付件内、
Mailpit / 数据库前置不满足），不是被静默跳过的功能。

`cp -r` 副本另经三项检查：
- `find … -type f -links +1` 为空 —— 证明是 `cp -r` 而非 `cp -al`
- `find … -type l` 为空 —— 证明没有符号链接
  （旧版只跑了前一条并据此声称「无 symlink」，那条命令只测硬链接，结论不成立）
- 副本内起站后 `/healthz` 与 `/` 均 **200**，`routes=1010` —— 证明未写死绝对路径

## 构建期附加产物

`clone/static/class-thumbnails.json` 由 `tools/gen_class_thumbnails.py` 生成
（路由 → 缩略图，465/465 覆盖）。改投卡片靠它换成落点课程自己的图；
重跑构建后需要一并重跑该脚本。

## 本轮（2026-08-30）另跑的实测

| 项 | 读数 |
|---|---|
| 声明路由全量 | 1010 条 → 200×1000 / 401×10，**非 200/401 为 0** |
| 站内链接闭合 | 328,337 处 `<a>`，1003 个去重目标 → **死链 0**；站外 `<a>` **0** |
| 资源闭合 | 11,237 个去重本地引用 → 200×11,148 / 404×87（**全部源站侧**，见 `scope/source-defects.md`）|
| 浏览器外发请求 | 30 页抽样 → **0**；JS 运行时错误 **0** |
| 交互实证 | 7 个页签全部可达、collapse 可开合、内联 handler 无 ReferenceError |
| 并发结算 | 同一订单 12 路并发确认 → 200×1 + 409×11 |
| 登录限流 | 同账号连错 12 次 → 401×5 + 429×7 |
| 参照完整性 | 缺参 400、不存在 404（enroll / progress / watchlist 三端点） |
| 两进程重启持久化 | session 与业务数据均存活 |
