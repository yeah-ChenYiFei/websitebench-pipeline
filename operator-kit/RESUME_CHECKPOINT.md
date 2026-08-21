# 环境续跑检查点

更新时间：2026-08-19（Asia/Shanghai）

## 已完成

- 唯一工作区：`D:\codework\websitebench-pipeline`。
- `Ubuntu-24.04` 已作为 WSL2 发行版安装到 `D:\WSL\WebsiteBench-Ubuntu`，默认用户为 `xhw`。
- Linux Node `v24.18.1`、npm/npx `11.16.0`、uv `0.11.7`、CPython `3.12.13` 和冻结项目依赖已安装。
- Playwright 1.61.0、Chromium 149、系统依赖、Xvfb 和字体已安装；无头烟雾测试通过。
- Prompt freshness 为 `15 passed`；两个 WebsiteBench CLI 可加载。
- Playwright MCP 与 Browser Use MCP 均完成真实 JSON-RPC 握手，缓存和临时文件定向 D 盘。
- 5 个薛皓文任务、通用提示词、站点启动块、教程视频转写和培训材料说明均已归档。
- 通用部署包已按 lockfile 安装；未连接 Cloudflare 或 Harbor。
- 微软 WSL `6.18.33.2` 自定义内核已在 D 盘构建并启用，只关闭 `CONFIG_X86_X32_ABI`；匹配的 `modules.vhdx` 已通过 `qemu-img check`。
- Harbor sandbox preflight 已通过：Landlock ABI 7、seccomp user notification 可用、x32 unavailable、enforcement probe 通过。
- 一键回滚脚本已保留并会验证恢复到 `6.18.33.2-microsoft-standard-WSL2`。
- 没有开始具体网站复刻，没有 commit、push、PR 或远程部署。

## 当前无内核级阻塞

当前运行 `6.18.33.2-microsoft-standard-WSL2-x32off`，WebsiteBench 权威测试通过。产物、来源、哈希、验证与回滚说明见 `operator-kit/CUSTOM_WSL_KERNEL.md`。

需要恢复微软默认内核时，在仓库根目录运行：

```powershell
.\operator-kit\scripts\rollback-wsl-kernel.cmd
```

## 用户回来后的顺序

1. 进入 Ubuntu，先运行 `passwd` 修改临时密码。
2. 选择第一个站点后，逐字确认该站的正式 `HUMAN_TRACE_TEXTS`、来源访问、登录、变更和资产保存边界。
3. 需要 SingleFile 时，由用户在独立浏览器 profile 中手工确认扩展权限。
4. 只有进入 Compose/Harbor 容器校准后再安装 Docker Desktop。
5. 达到本地验收标准后先准备差异与 PR 草案；commit、push、创建 PR 和部署仍需当次明确授权。

## 常用入口

- 总操作手册：`operator-kit/README.zh-CN.md`
- 新站提示词：`operator-kit/NEW_SITE_PROMPT_TEMPLATE.zh-CN.md`
- 5 站启动块：`operator-kit/XUEHAOWEN_SITE_STARTERS.md`
- 环境状态：`operator-kit/ENVIRONMENT_STATUS.md`
- WSL 环境脚本：`operator-kit/scripts/setup-wsl-environment.sh`
- 自定义内核与回滚：`operator-kit/CUSTOM_WSL_KERNEL.md`

Ubuntu 临时密码不写入本文件或仓库。
