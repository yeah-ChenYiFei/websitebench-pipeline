# WebsiteBench 新站后端接入规范

本规范规定新离线 clone 如何接入通用的账号、邮件、付款与数据库运行时。
通用 clone 报告只表达 `clean`、`findings` 或 `incomplete`，并始终要求维护者判断；
它不表达法律、合并、部署或再分发授权。

本文只改变未来接入的产品与运行时命名。历史 ClawBench 轨迹、证据哈希、
语料标识、捕获产物、已 vendored 的 runtime、兼容 schema 与其中记录的命令
字符串都是数据身份，必须原样保留；除非另有精确范围且可验证兼容的数据迁移，
agent 不得批量重命名、重写或重新解释它们。

## 何时必须接入

在实现任何持久账号、注册、登录、密码找回、验证码邮件、业务邮件、订单、
checkout、付款或业务数据库之前，先在该站的 scope/plan 中记录这些能力是否
适用。任一能力适用时，必须在实现这些能力前运行：

```powershell
websitebench-offline-clone backend scaffold --site materials/<site>
```

scaffold 会拒绝覆盖已有文件，也不会从 capability pack 推断本站的业务表。
它会生成唯一的 `backend/runtime.json` 运行合约、
离线 vendored 的 `websitebench` 运行时与
`clone/backend/site_backend_integration.py`。业务 schema、migration 与 seed
hook 仍由站点实现，但必须经该 integration seam 打开。

若上述能力都不适用，agent 仍必须在 scope/plan 中明确记录“通用后端不适用”
及原因；不得以未记录的本地脚本或临时数据库绕过本规范。

## 唯一运行合约

`backend/runtime.json` 是站点身份、数据库、会话、邮件、付款与部署 profile
的唯一合约。部署描述符只引用它；环境变量只能提供 secret，不能改变
`site_id`、数据库身份、付款货币、回跳 host/path 或其他冻结语义。

新代码使用：

```python
from websitebench.site_backend import SiteBackend

backend = SiteBackend.open("backend/runtime.json")
backend.lifecycle.initialize()
```

旧 `clawbench.*` import、`clawbench-*` CLI、`clawbench_site_binding` SQLite
表和旧 runtime schema 仅用于已有站点的兼容读取；不得用于新 scaffold 或新
集成。

## 隔离要求

- 每个站点都有唯一、稳定的 `site_id`，并使用独立 SQLite 文件、备份与 Docker
  named volume。
- `SiteBackend.open()` 必须校验数据库内的站点绑定。外站数据库、备份或 volume
  恢复到本站时必须 fail closed。
- 永久账户只存入本站 SQLite。同一邮箱可分别注册不同站点，但 A 站注册或密码
  绝不能让用户登录 B 站。
- session cookie 从 `site_id` 派生，必须是 `__Host-`、Host-only、Secure、
  HttpOnly、SameSite，且绝不设置父域 `Domain`。
- Redis 只可共享邮箱/IP 滥用预算；challenge、attempt、lock 与 verified ticket
  必须处于 `site/<site_id>` namespace。

## 邮件

可以复用同一 Resend 认证域名或发送地址，但每站必须在 runtime 中声明不同的：

- sender display name；
- subject、lead、expiry、footer 文案；
- template ID 与启用的 purpose。

模板只接受结构化纯文本字段，由运行时生成并转义 HTML/text。不得传入任意
HTML。验证码只持久化 salt/hash；不得写入数据库、日志、报表或 outbox 正文。
业务 outbox 只保存 template ID 和服务端变量快照，绝不保存 provider secret、
原始 provider 错误或消息正文。

## 付款

默认 profile 是 `local-sandbox`，必须提供确定的成功、拒绝与可重试场景。接口
只接受 owner、整数最小货币单位、currency、canonical fingerprint、幂等键与
不透明 scenario ID；绝不接收或保存卡号、CVV、有效期、银行或钱包凭据。

只有当前 payment scope v2 机器检查通过时，才可配置 `stripe-test`。它只
接受 test key 与每站独立 webhook secret，并在创建与最终提交时重新核对
`site_id`、flow、owner、金额、币种、fingerprint、回跳 host/path。任何 live
key、伪造 webhook、错配 metadata/host/path/currency 都必须拒绝。

付款范围先以 `materials/<site>/scope/payment-scope.json`（或等价的站点范围
文件）记录，并运行：

```powershell
websitebench-workflow check-payment-scope --proposal materials/<site>/scope/payment-scope.json
```

该检查将 site profile、付款 capability pack、当前 runtime/model、范围内
journey/entity/邮件隔离/安全付款合约归入不可自指的
`scope_subject_sha256`，并验证输入新鲜度、站点身份、cookie/Redis/database
隔离、邮件品牌和测试付款配置。检查本身不修改 profile、启用 adapter、连接
业务路由或部署。

新选择 payment overlay 的站点使用默认 `pre-change-proposal` 模式，并必须绑定
当前 profile 中的候选 blocker。历史 profile 已经选择 payment overlay 的站点
使用 `existing-overlay-audit`，`candidate_blocker_id` 必须为 `null`；该模式只对
现有选择和当前实现做哈希绑定复核，不补写人类批准、也不授权 live payment。

调用方必须在自己的 SQLite transaction 中消费付款结果，并把订单快照写入同一
transaction；最终提交必须重新校验当前服务端状态。

## 部署与机器验证

| Profile | 数据库 | 邮件 | 付款 |
| --- | --- | --- | --- |
| `offline-harbor` | 每站独立持久 SQLite | 本地 inbox/outbox | `local-sandbox` |
| `cloudflare-review` | 易失、按 seed 重建 | Redis + Resend | sandbox 或通过 scope 检查的 Stripe test |
| `docker-volume` | 每站独立 named volume | effects gateway + Resend | sandbox 或通过 scope 检查的 Stripe test |

Cloudflare review 必须明确报告其 ephemeral/reset-on-rebuild 性质，不能宣传为
持久化。长期状态使用 `docker-volume`；不同站点的 volume 和内部网络不得共用。

每次接入或迁移至少验证：跨站账号/密码/session/Redis ticket/付款 flow/备份/
volume 被拒绝；邮件品牌不同且无 OTP/正文/secret 泄露；付款成功、拒绝、重试、
重复、stale fingerprint、伪造金额和 foreign owner 均符合预期；migration 可
重复运行、备份可恢复、重启后数据保持。最后运行相关站点测试和部署 profile
检查。

报告通过的命令、runtime 路径、site ID、数据库/volume、邮件 purpose、付款与
部署 profile，以及仍未通过或缺少证据的机器门禁。
