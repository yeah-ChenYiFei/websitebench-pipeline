# Craigslist clone — backend completeness matrix

> Every user-visible journey maps to a real server-side implementation and an
> automated test. "后端必须全部实现" — no client-only fake state anywhere:
> refresh, re-login, restart, and second-user isolation are all server-backed
> (single bound SQLite via `websitebench.site_backend`).

| # | 旅程（用户要求） | 后端实现（app.py 路由 / craigslist_db） | 测试 |
| --- | --- | --- | --- |
| 1 | 入口 → housing 导航 | `GET /search/area/{region}?cat=hhh`；分类来自 `cl_categories` | test_app_surface::test_housing_navigation_from_entry |
| 2 | 发布 sublet（1BR/Annex/$2400/7-8月/furnished） | 向导：`/post/category|location|details|contact|photos|preview|publish`；`create_posting` 持久化 | test_backend_semantics::test_posting_publish_visible_in_listing_and_search（端到端发布 + 详情逐项匹配） |
| 3 | 按地区/类别浏览 | `/area/{region}`、`/search/area/{region}?cat=`；`section_postings` | test_app_surface::test_region_shells、test_public_routes_render |
| 4 | 价格/社区/日期/类别筛选 | `search_postings(min_price,max_price,postal,posted_today,bedrooms,housing_type,…)` | test_backend_semantics::test_search_filters_deterministic |
| 5 | 详情：描述/照片/价格/位置/回复 | `GET /view/d/{slug}/{code}`；`get_posting`/`posting_photos` | test_backend_semantics（详情断言）、test_app_surface::test_listing_detail_surface |
| 6 | 收藏/保存搜索 | `POST /{region}/housing/favorite/{id}`、`POST /search/…/save`；`cl_favorites`/`cl_saved_searches`（服务端持久化） | test_backend_semantics::test_favorite_persists_across_refresh_and_relogin、test_saved_search_persists |
| 7 | 账号/登录管理帖子 | `POST /account/login`（`sign_in` 会话轮换）、`POST /account/logout` | test_backend_semantics::test_login_logout_session_lifecycle |
| 8 | 选定类别/地区发帖 | 向导 step1–2 服务端校验 + `cl_posting_drafts` | test_backend_semantics::_publish_sublet（全向导） |
| 9 | 标题/价格/描述/属性/联系方式/地图 | step3–4；服务端字段校验（title/price/desc/postal/contact）；本地地图占位 | test_backend_semantics::test_posting_edit…（校验）、test_registration_validation… |
| 10 | 照片上传/排序/删除 | `POST /post/photos`（multipart）、`/reorder`、`/remove`；`cl_draft_photos` + 数据目录 | test_posting.photos（向导内） |
| 11 | 预览/发布确认 | `GET /post/preview`、`POST /post/publish` → 新 posting 行 + 确认页 | _publish_sublet 断言 publish 页 |
| 12 | 编辑/续期/重发/删除 | `POST /post/edit|renew|repost|delete/{id}`（owner-only 服务端权限） | test_backend_semantics::test_posting_edit_renew_repost_delete_lifecycle、test_posting_owner_only_permissions |
| 13 | 回复/联系流程 | `POST /{region}/housing/reply/{id}`：校验 + `cl_reply_messages` + 本地 outbox 投递 | test_backend_fullchain::test_reply_lands_in_outbox_and_persists、test_backend_semantics::test_reply_validation_and_delivery |
| 14 | 设置/举报/标记 | `POST /flag/{id}`（reason+note）→ `cl_flags` | test_backend_semantics::test_flag_requires_reason |
| 15 | 无结果搜索 + 返回路径 | `search_postings(query)` 空结果 → no-results 页 | test_backend_semantics::test_search_no_results_and_route_back |
| 16 | 登录入口（不提交凭据） | `GET /account/login`（页面） | test_app_surface::test_signin_verify_only_surface |
| 17 | 注册入口（不建号） | `GET /account/register`（页面） | test_app_surface::test_registration_verify_only_surface |
| 18 | 找回密码入口（不发信） | `GET /account/forgot`（页面） | test_app_surface::test_signin_verify_only_surface |
| 19 | 账户历史（最新项状态/详情/编辑/取消） | `GET /account/home`：`postings_for_account` + 状态 + 操作链 | test_backend_semantics::test_posting_edit…（账户页断言） |
| 20 | 空字段/未登录提示 | 服务端 422 内联校验；未登录 401 权限提示 | test_backend_semantics::test_signed_out_stateful_action_prompt、test_registration_validation_and_terms |
| 21 | 帮助/支持/联系（不泄露私数据） | `GET /about/help*`、`/contact` | test_app_surface::test_help_surface_no_private_data、test_contact_validation_and_sent |
| 22 | 404 品牌恢复视图 | 404 handler → branded not-found | test_app_surface::test_branded_not_found_preserves_navigation |
| 23 | 端到端 sublet 发布 | 全向导 + 详情匹配 | test_backend_semantics::test_posting_publish_visible…、test_backend_fullchain::test_registration_full_chain… |

## 业务约束（服务端强制 + 测试）

| 约束 | 实现 | 测试 |
| --- | --- | --- |
| 5 分钟/邮箱注册限流 | `cl_registration_events` + 可控时钟 | test_backend_semantics::test_registration_unique_email_and_rate_limit |
| 注册邮箱唯一 | LocalAuthStore + 服务端 409 | 同上 |
| 会话持久/登出失效 | `sign_in`/`sign_out` + `__Host-` cookie | test_login_logout_session_lifecycle |
| 仅 owner 可管理帖子 | `_owner_or_prompt` 403 | test_posting_owner_only_permissions、test_isolation_per_user_data |
| 用户数据隔离 | 服务端按 account_id 过滤 | test_isolation_per_user_data |
| 重置码单次/过期 | LocalAuthStore challenge 流程 | test_backend_fullchain::test_reset_code_single_use |
| 确定性重置 | `/__admin/reset` + seed | test_backend_lifecycle::test_seed_is_deterministic |
| 运行时零外发请求 | CSP + 无远端引用 | test_no_remote_refs、live_check |

**结果**：`python -m pytest tests/ -q` → **71 passed**；`verify --section static` → clean；浏览器等效检查 29/29 通过。

## 管理接口（benchmark admin contract）

| 端点 | 用途 | 认证 |
| --- | --- | --- |
| `POST /__admin/reset` | 确定性重置到种子状态 | `X-WebsiteBench-Admin-Token` |
| `GET /__admin/mail/query` | 查询本地 outbox（registration/password-reset/posting-reply），含验证码明文 | `X-WebsiteBench-Admin-Token` |

## 会话 cookie（按协议自适应）

- HTTPS：`__Host-websitebench-craigslist-session` + Secure + HttpOnly + SameSite（生产标准）
- HTTP（本地演示）：`websitebench-craigslist-session`（无 `__Host-`/Secure，浏览器可发送）
- 两者都 host-only、HttpOnly、SameSite=Lax
