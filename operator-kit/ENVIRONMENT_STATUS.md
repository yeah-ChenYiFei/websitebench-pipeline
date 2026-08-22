# 环境检查记录

检查日期：2026-08-19（Asia/Shanghai）

## 工作区与磁盘

- 唯一工作区：`D:\codework\websitebench-pipeline`
- 上游：`https://github.com/tuxyw123/websitebench-pipeline`
- 分支/基线：`main` / `77df7517f1a7aaf4843e0b334412efa75b638bf1`
- 仓库局部配置：`core.longpaths=true`
- WSL 发行版数据：`D:\WSL\WebsiteBench-Ubuntu\ext4.vhdx`；内核源码与编译树位于该 D 盘 VHDX 的 ext4 中
- 最后复核可用空间：C 盘约 6.52 GB，D 盘约 20.96 GB；自定义内核、模块 VHDX 与可复现编译材料均保留在 D 盘

`D:\ubantu (2)` 与 `D:\ubantu64` 是既有 VMware 虚拟机，不是 WSL 发行版；没有移动、转换或覆盖。

## Windows 主机

| 组件 | 已验证状态 |
| --- | --- |
| Git | 2.50.1.windows.1 |
| Node.js / npm | 24.18.1 / 11.16.0 |
| uv | 0.11.7 |
| GitHub CLI | 2.96.0 |
| Edge | 已安装 |
| Microsoft.WSL | 2.7.11.0 |
| Docker daemon/Desktop | 未安装；当前阶段不需要 |
| OpenCLI | 未安装；仓库允许记录 `opencli-unavailable` |

## WSL2 Ubuntu

- 发行版：`Ubuntu-24.04`，WSL 版本 2，默认用户 `xhw`
- 安装位置：`D:\WSL\WebsiteBench-Ubuntu`
- 当前内核：`6.18.33.2-microsoft-standard-WSL2-x32off`
- 微软默认回滚目标：`6.18.33.2-microsoft-standard-WSL2`
- Linux Node.js：`v24.18.1`，下载归档通过固定 SHA-256 校验
- Linux npm/npx：`11.16.0`
- Linux uv：`0.11.7`，下载归档通过固定 SHA-256 校验
- 项目 Python：受管 CPython `3.12.13`
- 项目依赖：`uv.lock` 冻结同步完成，52 个包，WebsiteBench editable package 可加载
- Playwright：Python `1.61.0`；Chromium/Chrome for Testing `149.0.7827.55`
- Playwright 系统依赖、Xvfb 与中英文字体已安装

临时 Ubuntu 密码没有写入脚本、仓库或本文档。恢复使用后应先在 Ubuntu 中执行 `passwd` 修改。

## 最小验证结果

| 验证 | 结果 |
| --- | --- |
| `tools list` | 通过，输出 4 个诊断工具 |
| Prompt freshness | `15 passed` |
| `websitebench-offline-clone --help` | 通过 |
| `websitebench-harbor --help` | 通过 |
| Chromium 无头烟雾测试 | 通过：启动、设置页面、读取标题/DOM、关闭 |
| Harbor sandbox preflight | 通过：`1 passed in 0.20s` |

没有运行与当前环境无关的全仓库审计，也没有为了通过测试而移除或降低隔离检查。

## 自定义 WSL 内核

已按用户授权从微软官方 `linux-msft-wsl-6.18.33.2` 标签构建自定义内核，只关闭 `CONFIG_X86_X32_ABI`，并保留 `CONFIG_IA32_EMULATION`、`CONFIG_COMPAT`、Landlock 与 seccomp。当前正式指纹为：

```text
architecture=x86_64
landlock_abi=7
seccomp_user_notification=true
x32_unavailable=true
enforcement_probe_passed=true
```

内核产物位于 `D:\WSL\Kernels\6.18.33.2-x32off`，用户级 `.wslconfig` 同时指定 `bzImage` 与匹配的 `modules.vhdx`。构建来源、精确提交、配置差异与 SHA-256 见 `build-manifest.json`；详细说明见 `operator-kit/CUSTOM_WSL_KERNEL.md`。

一键回滚入口：双击 `operator-kit\scripts\rollback-wsl-kernel.cmd`，或在仓库根目录运行：

```powershell
.\operator-kit\scripts\rollback-wsl-kernel.cmd
```

本机切换前没有 `.wslconfig`，因此回滚会把受管配置改名保留，重启 WSL 并严格验证微软默认 release；不会删除自定义内核产物。

为避免未来覆盖用户级全局设置，启用脚本在发现预先存在的 `.wslconfig` 时会失败即停，不自动重写或猜测合并。

## MCP 状态

- 项目级 `.codex/config.toml` 使用官方稳定的 `[agents]` 配置，单会话最多 3 个子 Agent 线程；当前模型运行时为 V2。
- Playwright MCP 固定为 `@playwright/mcp@0.0.79`，明确使用已安装的 Edge 151、无头与内存隔离会话；真实 JSON-RPC `initialize` 及纯本地页面 `browser_navigate` 调用成功。
- Browser Use 固定为 `browser-use[cli]==0.12.6`；真实 JSON-RPC `initialize`、`tools/list`、纯本地页面 `browser_navigate` 和 `browser_close_all` 均成功。
- 两套 MCP 的 npm、uv、Python、Playwright、XDG、profile 与临时目录均定向到 `D:\codework\.websitebench-tools`。
- Browser Use 的安全开关保持启用；Browserbase 未配置，因为需要独立密钥、费用和第三方数据边界。
- Codex Desktop 应用内置 `codex.exe` 不能从普通子进程直接执行（WindowsApps 返回拒绝访问），因此使用 TOML 解析、服务端真实握手与当前 Desktop 会话加载结果验证配置。

## 通用部署包

`deploy/generic-offline-clone/` 已按 lockfile 执行 `npm ci --no-audit --no-fund`。Windows 测试为 25 项：22 通过、2 跳过、1 项仅因 Windows 无符号链接权限失败。示例配置的 `--check-only` 正确因不存在 `materials/taskrabbit/clone` 而停止；没有伪造 candidate，也没有执行 Wrangler、Cloudflare、Harbor 发布或任何远程部署。

## 任务材料

- 薛皓文的 5 行分配已由用户直接提供，逐项保存到 `operator-kit/assignments/xue-haowen.json`，启动块见 `operator-kit/XUEHAOWEN_SITE_STARTERS.md`。
- 用户已提供最新提示词文档全文；Meetup、example.com 和其中的命令只按培训材料解析，见 `operator-kit/SUPPLIED_PROMPT_DOCUMENT_NOTES.md`。
- 教程视频已用 `faster-whisper 1.2.1`、`small`、CPU int8 在本机完成转写，没有上传。原始转写位于 Git 忽略的 `reviews/tutorial-video/`，整理结果见 `operator-kit/TUTORIAL_VIDEO_NOTES.md`。
- SingleFile 尚未安装；Chrome/Edge 扩展的权限确认需要用户在浏览器 UI 中完成。

## 明确未执行

- 没有开始 Bean Box、BeerAdvocate、BetterHelp、Blinkist 或 Bluemercury 的具体复刻。
- 没有创建真实账号、评论、预约、订阅、订单或付款。
- 没有 commit、push、PR、Harbor 发布或公网部署。
- 没有读取或复制日常浏览器 profile、Cookie、Token 或其他凭据。
- 没有安装 Docker Desktop；等首站确实进入 Compose/Harbor 容器校准再决定。
