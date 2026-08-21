# Bluemercury 离线复刻验收说明（Assignment 20，r28）

## 交付定位

本交付物是仅供本地评测的 Bluemercury 离线功能候选与视觉复核材料。正式 human trace 保持原文：

`[781] On the Bluemercury website, purchase a skincare product, add to cart, and proceed to checkout`

源站仅进行了匿名、只读证据采集。源站登录、加购、结账、下单、付款和真实邮件均未执行。候选站点只接受合成身份、合成地址和 `local-sandbox` 支付。

## 已实现功能

- 首页、桌面/移动主导航、公告栏、搜索入口、分类入口及首页主要链接均具有本地可访问目标。
- 本地目录包含 250 条可搜索、可打开详情的商品数据；其中 67 条为有来源证据的 skincare 商品。源站显示的 `(1707)` 仅作为来源参考计数，不伪装为本地商品数量。
- 分类页、搜索成功状态、搜索零结果、商品网格、商品详情、商品图片切换、可用变体切换和价格更新。
- 商品数量增减、加入购物袋、空/非空购物袋、更新数量和移除商品。
- 由商品详情经过加购、购物袋、合成地址、`local-sandbox` 支付至确认页的完整本地核心 journey。
- `local-sandbox` 的 approved、declined、retryable 三种结账结果；不会产生真实扣款、订单、邮件或发货。
- 本地注册、登录、退出、账户页和愿望单；只允许 `@example.test` 合成邮箱边界。
- 密码使用带盐 `scrypt-v1` 哈希；会话、购物袋、愿望单和订单按站点与本地身份隔离。
- 本地 SQLite 持久化、重启恢复、受令牌保护的 reset、owner/foreign order 隔离及无支付凭据留存。
- 250 个本地商品资产及页面字体、Hero、PDP 图片全部本地化；运行时不请求源站。
- Harbor same-id site/instance、编译入口、健康检查、200 个 v2 评测 case 和 15 个 trusted runner。
- 冻结 viewport 覆盖：桌面 `1440×900`、移动 `390×844`；首页、PDP、分类和空购物袋均有 Source/Candidate 截图轨迹。

## 当前不能实现或不能宣称的内容

- 不能宣称整体视觉已经完全不可区分。最终独立无标签盲测通过 5/8：桌面首页、桌面分类、桌面空购物袋、移动分类、移动空购物袋通过；桌面 PDP、移动首页、移动 PDP 仍可区分。
- PDP 评分星标、定位图标、缩略图边缘和源站自身的破图状态仍有差异。候选不会故意复制源站临时破图失败态。
- 移动首页深色 Hero 卡片右下圆角及图片衔接仍有差异；该 finding 已达到两轮无可测改善的停止条件。
- Source PDP 的评论、临床说明、FAQ、编辑内容等完整下半页证据与资产不足，因此候选下半页较短。
- 不提供真实 Bluemercury 账户登录、源站购物袋、源站结账、真实订单、真实付款、真实邮件或真实发货。
- Harbor 不能标记为 complete/scorable：当前为 `draft`、`reference_observations=pending`、`scorable=false`，缺少维护者批准的独立 Reference，不能使用 candidate observations 冒充。
- OpenCLI binary 不在 PATH，bag/catalog OpenCLI replay 证据不可用。
- D: 盘原位 full verify 受 WSL Landlock/DrvFS 限制为 `incomplete`；精确副本在 WSL ext4 上为 `clean`。不能把 ext4 结果描述为原位 clean。
- 权利与再分发状态为 `unknown`；本交付不包含公开发布、远程部署、push、PR 或再分发授权。

## 验证摘要

- pytest：23 passed，退出码 0。
- 桌面浏览器：15/15；移动浏览器：15/15；断言失败、外部请求、阻断请求、失败请求和 console error 均为 0。
- 静态诊断：clean；资产 256/256；远程运行时引用 0；secret finding 0。
- runtime semantics：身份隔离、持久化、reset 权限和敏感数据留存检查全部通过，退出码 0。
- Harbor seed：compile/health 通过，trusted runners 15/15；Harbor validate 恰好 200 cases、missing 0，退出码 0。
- 独立代码审查：APPROVE，无 CRITICAL/HIGH/MEDIUM/LOW finding。

## 验收建议

建议按“最终本地功能候选 + 初步视觉复核材料”提交验收。适合验收本地 P0/P1 功能、离线资产闭包、runtime 隔离与已通过的 5 个视觉 checkpoint；不应标记为整体视觉不可区分、Harbor complete/scorable、rights-cleared 或可公开发布。
