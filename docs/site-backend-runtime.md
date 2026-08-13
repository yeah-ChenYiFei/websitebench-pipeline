# 通用离线 Clone 站点后端

`websitebench.site_backend` 把数据库生命周期、品牌化邮件、模拟付款和部署
profile 封装成一个可复用深模块。共享的是接口、状态机和实现代码；永久
账号、订单、付款记录、SQLite 文件和 volume 必须按站点独立。

## 接入顺序

只有站点前端 gate 已由机器验证流程确认后，才执行：

```powershell
websitebench-offline-clone backend scaffold --site materials/<site>
```

scaffold 会拒绝覆盖已有文件，也不会从 capability pack 猜测业务表。
它生成 `backend/runtime.json`、可离线 vendoring 的 site-backend/auth
运行时，以及 `clone/backend/site_backend_integration.py`。该接入 seam
始终把 runtime 的 `site_id` 传给 `LocalAuthStore`。站点继续拥有自己的
migration/seed hook。

`backend/runtime.json` 是唯一运行合约，内容包括站点身份、安全数据库
路径、hook 名称、session cookie、邮件品牌文案、付款参数和三种部署
profile。部署 v2 描述符只引用该文件。环境变量只能注入 secret，不能
改写 `site_id`、host/path、currency 或数据库身份。

## 数据库与账号隔离

打开后端：

```python
from websitebench.site_backend import SiteBackend

backend = SiteBackend.open(
    "backend/runtime.json",
    migration_hook=migrate_site,
    seed_hook=seed_site,
)
backend.lifecycle.initialize()
```

每个新数据库都包含唯一的 `websitebench_site_binding(site_id)`。错误站点的
数据库、备份或挂载会 fail closed。Amazon 已迁移到 canonical binding；检测
到其旧 ClawBench binding 时，只允许在验证 Amazon 业务 schema provenance
后执行 copy-only 迁移：原库字节保留为相邻 legacy 副本，canonical 副本完成
integrity/foreign-key/binding 校验后才原子替换工作路径。其他冻结 compatibility
runtime 仍使用 `clawbench_site_binding(site_id)`。canonical 与 legacy runtime
都会扫描另一 namespace，发现另一 binding 或双 binding 时一律拒绝。路径必须
位于运行合约的数据根目录内；绝对路径逃逸、`..` 和 symlink/junction 逃逸
都会被拒绝。

新站点认证必须把相同 `site_id` 传入：

```python
auth = LocalAuthStore(database_path, site_id=backend.config.site_id)
```

同一邮箱可以在 Amazon 和 edX 分别注册，但两边账号、密码和 session
完全独立。A 站注册不会在 B 站创建账号。cookie 名称从站点 ID 派生，
使用 `__Host-`、Host-only、Secure、HttpOnly、SameSite，永不设置父域
`Domain`。

生命周期接口：

- `initialize()`：校验绑定、integrity/foreign keys，并幂等运行 hook；
- `prepare_bound_site_migration()`：仅对已经绑定到当前 `site_id` 的旧业务
  schema 延后完整性检查；站点修复后必须立即执行 `health()`；
- `health()`：返回绑定、迁移和 SQLite 健康状态；
- `backup(path)`：使用 SQLite 一致性 backup；
- `restore(path)`：先在临时副本校验绑定、完整性和 migration，再替换；
- `reset()`：只重建已验证的当前站点数据库；
- `reset_embedded(connection)`：在站点已有 transaction 中清除通用状态。

## 邮件

同一 Resend 认证域名或发送地址可以复用，但每站必须声明不同的 sender
display name、subject、lead、expiry/footer。runtime 只接受结构化纯文本，
组件统一转义并生成 text/HTML，不接受任意 HTML。

`mail.issue()` 用于验证 purpose；`mail.enqueue()` 用于不含 secret 的业务
邮件。业务 outbox 保存投递所需的规范化收件人、收件人 digest、template
ID 和服务端变量快照；收件人属于站点私有数据，不得进入日志或跨站共享。
outbox 不保存渲染正文、provider secret 或原始 provider 错误。调用方
传入 connection 时必须已有 active transaction；投递提供原子 claim、
有限重试、幂等处理和 crash replay。

需要公网投递时，`EffectsMailDelivery` 只会把已 claim 的非 secret 业务
outbox 传给站点内部 `resend.internal/business-emails`：payload 仅含
`purpose`、`template_id`、收件人与服务端变量。effects gateway 从冻结的
runtime 模板重新验证变量、拒绝任何带 secret variable 的 purpose，并自行
生成转义后的 subject/text/HTML 与 From；应用不能发送任意 HTML、正文或
provider credential。业务写入必须先 commit，之后才可尝试投递；失败只把
job 留为带安全 error category 的 `PENDING` 重试，不会撤销已确认订单或
enrollment。

注册/找回 OTP 只持久化 salt/hash。明文仅短暂存在于签发进程；进程重启
后无法重放尚未发送的 outbox，但已经交付给用户的 code 仍可由 hash-only
flow 校验。只有旧 schema 中含明文 OTP 的 pending flow 会在迁移时失效并
要求重新签发，旧明文绝不搬入新表。共享 Redis 只共享全局邮箱/IP 滥用
预算；challenge、attempt、lock 和 verified ticket 必须位于
`site/<site_id>`。

## 付款

默认 `local-sandbox` 提供确定性批准、拒绝和重试。调用方只提交 owner、
整数最小货币单位、currency、canonical fingerprint、幂等键和不透明
scenario ID。接口不接收或保存卡号、CVV、有效期、银行路由或钱包凭据。

```python
flow = backend.payments.create_intent(
    owner="account-123",
    amount_minor=2599,
    currency="USD",
    fingerprint=canonical_cart_fingerprint,
    idempotency_key="checkout-42",
)
attempt = backend.payments.attempt(
    flow_id=flow["flow_id"],
    owner="account-123",
    amount_minor=2599,
    currency="USD",
    fingerprint=canonical_cart_fingerprint,
    scenario_id="sandbox-approved",
    idempotency_key="checkout-42-attempt-1",
)

with backend.lifecycle.connection(transaction=True) as connection:
    approval = backend.payments.consume_approval(
        connection,
        flow_id=flow["flow_id"],
        owner="account-123",
        amount_minor=2599,
        currency="USD",
        fingerprint=canonical_cart_fingerprint,
    )
    create_site_order(connection, approval)
```

付款 flow、attempt 和 immutable event 都带 `site_id`、owner、金额、币种、
fingerprint、幂等键与 `is_simulation=true`。新 attempt 或上游 fingerprint
变化会让旧 approval 失效。调用方必须像上例一样，把
`consume_approval()` 放在 transaction 内的第一项业务写操作之前；成功消费
后再写订单，因此订单失败会把 approval 消费一同回滚。最终事实不匹配时，
组件在释放 SQLite 写锁前提交 `APPROVAL_INVALIDATED_FINAL_STATE`，随后恢复
一个空的调用方 transaction 并抛出拒绝；不存在旧 approval 可被并发连接抢先
消费的 rollback/restart 窗口，也不会提交部分订单。

可选 `stripe-test` adapter 只接受 `sk_test_`，且每站使用独立 webhook
secret。创建 Session 和最终提交都会核对站点、flow、金额、币种和
fingerprint；回跳 host/path 与 line-item 上限来自冻结 runtime。任何 live
key、伪造 webhook、错误 metadata/host/path/currency 都被拒绝。普通
`attempt()` 永远不能批准 Stripe flow；服务端必须调用
`attempt_verified_stripe()` 并传入不可由浏览器序列化的 provider verifier
callable。组件通过该 verifier 重新取得/认证 Session，再独立核对 test
mode、paid/complete、site、flow、owner、金额、币种和 fingerprint。

## 部署

| Profile | SQLite | 邮件 | 付款 |
|---|---|---|---|
| `offline-harbor` | 每站独立并跨进程重启持久 | 本地安全 inbox/outbox | `local-sandbox` |
| `cloudflare-review` | 易失，重建后回到 seed | Redis + Resend | 可选 `stripe-test` |
| `docker-volume` | 每站独立命名 volume | effects gateway + Resend | sandbox 或 Stripe test |

Cloudflare Container 磁盘是 ephemeral；review profile 必须报告
reset-on-rebuild，不能宣传持久化。长期状态使用 `docker-volume`，每站
生成独立 app、effects gateway、内部网络和 volume；effects gateway
不能挂载站点数据库。

v2 容器在执行站点命令前会从冻结 runtime 解析精确 hook，并在该站
`/data` 映射中初始化或校验 site binding；错误站点 volume 会在提供公共
流量前 fail closed。Compose 生成器会转义模板中的 `$`，容器收到的仍是
`${code}`/`${minutes}`，不会被 Compose 当作宿主环境变量展开。
Node 部署器不维护第二份 backend-runtime validator；v2 prepare/dry-run
同步调用 Python `websitebench.site_backend` 的规范 validator，因此非法 hook、
邮件 placeholder、sandbox outcome、Stripe 或 profile 语义在构建阶段与
容器运行阶段得到相同判定。

通用部署器位于 `deploy/generic-offline-clone`：

```powershell
node scripts/prepare.mjs --config deployment.amazon.v2.json --check-only
node scripts/deploy.mjs --config deployment.amazon.v2.json --dry-run
```

真实部署还需要 `--yes`、短期 digest-bound authorization 文件，以及通过
`websitebench-offline-clone status --site materials/<site_id>`。
部署成功也不提升 Harbor、rights、机器验证或 technically-verified。

## 迁移状态

Amazon 已通过加法 migration 接入站点绑定和通用 mail/payment 表；历史
订单与付款快照保留，新付款 approval 与订单在同一 transaction 提交。
Amazon Stripe Worker 仅保留站点薄配置，公共代理不含 Amazon 页面、购物
车或 URL 业务模型。Stripe test approval 和订单邮件均写入通用账本；
旧 `payment_attempts`/`email_outbox` 作为兼容投影继续可读，其邮件
claim/结果与通用 job 在同一 transaction 内同步。旧投影把一次失败显示为
可人工重试的 `SMTP_FAILED`，此时通用 job 仍是带安全错误分类的
`PENDING`；重试成功后两者分别进入 `SMTP_SENT`/`SENT`。

已绑定到 Amazon 当前 `site_id` 的旧数据库可以通过
`prepare_bound_site_migration()` 先运行加法/修复 migration，再执行最终
`health()`；该 seam 在读取到缺失或外站 binding 时立即拒绝，因此不会认领
任意 SQLite。尚未绑定的历史 Amazon 数据库还必须明确
`legacy_unbound_migration=true`，并由具名操作方执行一次显式迁移授权。其
入口是
`server.py --authorize-legacy-site-binding`；它先验证可识别的 Amazon
表/列 provenance，再调用兼容 seam `prepare_legacy_migration()`。普通
server 启动和通用容器 preflight 永远不会代替该授权。站点 migration
完成后必须立即调用 `health()`，完整性通过前不得启动公共服务。新
scaffold 禁止使用这两个兼容 seam。

edX 的非付款基础设施已迁移到 canonical WebsiteBench runtime：代码导入、
vendored root、数据目录环境变量、管理员 header、站点绑定、Host-only
Secure cookie 和邮件品牌均使用 WebsiteBench 接口。既有未绑定 edX
SQLite 只允许通过
`websitebench_edx_site_backend_migration.migrate_unbound_edx_database()`
在同目录副本上迁移；迁移会验证 edX migration provenance、保留原始字节、
原子安装通过 binding/integrity/foreign-key 检查的副本。普通启动不会自动
认领未绑定数据库。

edX 候选已完成代码级加法 migration `0009_site_backend_payment_overlay`：
它把 checkout 映射到站点专属通用 payment flow，在原 SQLite transaction
中消费 approval、写入订单/enrollment 与 `enrollment-receipt` outbox；
Stripe return/webhook 只使用 server 重新读取的 test Session。`stripe-test`
profile 的收据在 commit 后经上述受限 effects gateway 投递，投递失败不会
改变付款结果。`deploy/generic-offline-clone/deployment.edx.v2.json` 只从
edX runtime 取得 `edx.website-bench.com`、USD、回跳/webhook path 和
Stripe test secret 名称，并可做 dry-run；Cloudflare review 仍是 ephemeral。

这只是受控候选，不表示已获准公网启用。当前 site profile 尚未加入
`payment` overlay，且历史 proposal 的 approval 已因运行合约变化失效。
新的
`materials/edx/scope/site-backend-payment-scope-refresh-proposal.json` 将
当前 profile、scope、runtime/model 与 payment pack 绑定到精确
`scope_subject_sha256`
`3d300c9c9b920188e8f63df37747f2170356defda5f40921cb95efb0b14383ad`，目前
为 `pending`。只有当前 payment scope v2 对这个精确 hash 检查通过后，才可加入
overlay；该决定仍不部署、也不授予 Harbor、rights、fidelity 或 release。
可用下列只读门禁检查：

```powershell
websitebench-workflow check-payment-scope --proposal materials/edx/scope/site-backend-payment-scope-refresh-proposal.json
```

`pending` 的非零结果是预期安全停点；不得把它解释为可部署授权。

## 验证清单

至少运行：

```powershell
pytest -q tests/site_backend tests/local_clone_auth tests/public_clone_auth
cd deploy/generic-offline-clone
npm test
node scripts/deploy.mjs --config deployment.amazon.v2.json --dry-run
node scripts/deploy.mjs --config deployment.edx.v2.json --dry-run
```

另外需要站点自己的后端、浏览器、migration/backup 测试，以及有 Docker
daemon 时的容器替换持久性验证。任何未完成的 Harbor、rights、后端语义或
自动化浏览器门禁必须继续显示为 pending/blocked。
