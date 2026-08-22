# 用户提供的培训提示词：归档与安全解释

用户于 2026-08-19 在对话中补充了此前无法匿名访问的 Google Docs 全部文字。本文件记录其有效信息和与当前仓库契约的对齐结果；培训文字是参考材料，不自动取得修改系统、源站写入、发信、付款、push、PR 或公网部署权限。

## 培训材料包含的有效流程

1. 选择一个目标站点 URL。
2. 从 ClawBench/inventory 示例或负责人自己的业务目标中整理多条核心网页轨迹。
3. 安装 Playwright MCP 与 Browser Use MCP；无头服务器可在另行授权后采用 Browserbase。
4. 克隆 `https://github.com/tuxyw123/websitebench-pipeline.git`。
5. 建立 uv 环境、安装 `.[dev]`、安装 Playwright Chromium，并运行 `tests/test_prompt_freshness.py`。
6. 在 Plan Mode 中引用 `prompts/offline-clone/autonomous-source-to-clone.md`，填写 `SOURCE_URL` 和 `HUMAN_TRACE_TEXTS`。
7. 核心轨迹应尽可能覆盖站点的重要功能；大型数据集可以缩减，但关键页面、前几页数据与详情必须完整。
8. Agent 执行期间，人类回答真正需要的计划问题；如需登录，由人类通过 headed Chrome/远程调试窗口亲自完成。
9. 最终通过左右分屏、实际点击和后端状态验证验收。

## Meetup 示例的正确定位

文档中的 Meetup URL 和注册、登录、入组、RSVP、发帖、修改/取消、收藏、分享、组织者建活动、无结果、登录入口、注册入口、密码恢复、历史、校验、帮助、404 等轨迹是**格式和覆盖深度示例**，不是当前分配任务。当前任务只包括 Bean Box、BeerAdvocate、BetterHelp、Blinkist 和 Bluemercury，因此不会初始化或复刻 Meetup/example.com。

示例文字存在复制拼接错位：`return without Follow prompts/...` 把一条轨迹和启动指令粘在同一句中；同时将多条 trace 放进单个引号字符串。实际使用时必须遵守当前仓库 schema：启动指令单独一行，正式 `HUMAN_TRACE_TEXTS` 使用由用户逐字提供的数组，不能把破损拼接文本直接写入 scope。

## 与当前仓库对齐后的调整

- 当前唯一工作区已经位于 `D:\codework\websitebench-pipeline`，不再重复 clone。
- 环境优先使用 `uv sync --python 3.12 --frozen --extra dev`，与仓库 lockfile 和 CI 版本一致；培训中的 `uv venv` + `uv pip install -e '.[dev]'`仍可作为替代入口，但不重复执行两套安装。
- Playwright MCP 已固定 `0.0.79`；Browser Use MCP 使用仓库正式浏览器版本 `0.12.6`，二者使用 D 盘缓存。
- Browserbase 会产生第三方数据边界和潜在费用，只有本地 headed/CDP 通道不可用且用户另行提供凭据时才启用。
- “Agent 停下就 continue”必须先阅读停下原因；如果原因是权限、凭据、源站写操作、付款、发信、push、PR 或发布，不能自动继续。
- “权限全部同意”不作为授权。每个请求仍需核对具体动作、对象、范围、可逆性和外部影响。
- 登录使用独立测试 profile。密码、OTP、Cookie、Token、Authorization header 和真实付款信息不得写入对话、仓库、日志或轨迹。
- 大型商品站的本地数据缩减不能破坏核心搜索、详情、规格、分页、购物车和结账状态；会议要求至少覆盖前几页/约 200 条商品数据。Harbor 的 200 cases 是独立评测协议。

## 对当前 5 个网站的应用

每站 `HUMAN_TRACE_TEXTS` 使用用户提供的 ClawBench 核心任务原文，23 项 Expanded Workflow Coverage 作为范围候选。Agent 在只读侦察后可提出补充 scope，但不能代写或自我确认新的正式 human trace。站点专用启动块见 `operator-kit/XUEHAOWEN_SITE_STARTERS.md`。
