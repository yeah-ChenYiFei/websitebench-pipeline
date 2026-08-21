# WebsiteBench 自定义 WSL 内核与一键回滚

状态日期：2026-08-19（Asia/Shanghai）

## 当前状态

- 当前 release：`6.18.33.2-microsoft-standard-WSL2-x32off`
- 微软默认回滚 release：`6.18.33.2-microsoft-standard-WSL2`
- 发行版：`Ubuntu-24.04`
- 用户级配置：`%USERPROFILE%\.wslconfig`
- 内核产物：`D:\WSL\Kernels\6.18.33.2-x32off\bzImage`
- 模块产物：`D:\WSL\Kernels\6.18.33.2-x32off\modules.vhdx`
- 构建清单：`D:\WSL\Kernels\6.18.33.2-x32off\build-manifest.json`

`.wslconfig` 是 WSL2 全局配置。当前主机只有 `Ubuntu-24.04` 这一套 WSL 发行版；已有 VMware 目录 `D:\ubantu (2)` 与 `D:\ubantu64` 未被改动。

## 来源与最小配置差异

- 官方仓库：`https://github.com/microsoft/WSL2-Linux-Kernel.git`
- 精确标签：`linux-msft-wsl-6.18.33.2`
- 精确提交：`c21a03b2943d147c280bdf32530d4fe6badfd6bd`
- 源码归档 SHA-256：`21f28efed81a1c097d249917000eed9ca70e8f90bfeebc687ea9b559d5310906`

先用本机 GCC 13.3/binutils 2.42 对微软基线执行 `olddefconfig` 规范化，再应用变更。规范化基线与最终配置的语义差异严格只有：

```text
 LOCALVERSION "-microsoft-standard-WSL2" -> "-microsoft-standard-WSL2-x32off"
 X86_X32_ABI y -> n
```

明确保留：

```text
CONFIG_IA32_EMULATION=y
CONFIG_COMPAT=y
CONFIG_SECURITY_LANDLOCK=y
CONFIG_SECCOMP=y
CONFIG_SECCOMP_FILTER=y
```

## 产物校验

| 产物 | SHA-256 |
| --- | --- |
| `bzImage` | `8fd7c81ccb795f7e4e962a59fdc63bbc2a08f3a1a56730b80e35362252ed4650` |
| `modules.vhdx` | `5ef24befaabfb7caabdadf9f9f87012e92883bb2bae2ab26288ce7c1e2c3b2e6` |
| `config` | `8f82b7258c145c31eb6efff5b1fed29b9611e76b5dc68ebbc956286088e54309` |
| `config.diff` | `9e1914c70071cf10c59f9c7da04ec57214c70823f81c32842b5ecc3a0047dade` |

`modules.vhdx` 由微软仓库自带的 `Microsoft/scripts/gen_modules_vhdx.sh` 生成，随后执行 `qemu-img check`，结果为 `No errors were found on the image.`。启用脚本会在写 `.wslconfig` 前再次校验固定的 manifest schema、官方标签、提交、源码归档 SHA-256，以及内核、模块、配置和配置差异的 SHA-256。

## 实测验收

WSL 健康检查通过：C/D 挂载、D 盘工作区读写权限、cgroup v2、systemd、DNS、GitHub API HTTPS、匹配模块目录与 `bridge.ko` 均正常；内核日志未发现 panic、Oops 或 general protection fault。

WebsiteBench 权威测试：

```text
tests/harbor/test_deterministic_v2.py::test_sandbox_preflight_records_required_kernel_features
1 passed in 0.20s
```

运行态指纹：

```json
{
  "architecture": "x86_64",
  "enforcement_probe_passed": true,
  "landlock_abi": 7,
  "schema_version": "websitebench.harbor.sandbox-runtime.v1",
  "seccomp_user_notification": true,
  "x32_unavailable": true
}
```

## 一键回滚到微软默认内核

在仓库根目录双击或执行：

```powershell
.\operator-kit\scripts\rollback-wsl-kernel.cmd
```

回滚脚本会：

1. 校验活动 `.wslconfig` 未被意外修改；
2. 关闭全部 WSL2 实例；
3. 本机切换前不存在 `.wslconfig`，因此把受管配置改名为 `.wslconfig.websitebench-disabled-<时间戳>`；
4. 再次关闭并启动 `Ubuntu-24.04`；
5. 严格要求 `uname -r` 等于 `6.18.33.2-microsoft-standard-WSL2`；
6. 保存回滚结果，并把活动状态文件改名归档；
7. 保留所有自定义内核产物，便于诊断或再次启用。

如果活动 `.wslconfig` 在启用后被人工修改，脚本会失败即停；只有先审阅差异后才可显式运行 `rollback-wsl-kernel.ps1 -Force`。使用 `-Force` 时，脚本会先把漂移后的当前配置复制到带时间戳的归档文件，不会静默丢弃人工修改。

启用脚本发现预先存在的 `.wslconfig` 时会直接停止，不会覆盖，也不会猜测合并。必须先由人审阅现有的内存、CPU、网络、swap、代理及其他 section，安全合并 `kernel` 和 `kernelModules` 后再建立专用流程。

## 再次启用

回滚成功后，执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\operator-kit\scripts\enable-custom-wsl-kernel.ps1
wsl.exe -d Ubuntu-24.04 -u xhw -- uname -r
```

启用脚本会建立一份新的回滚基线。预期 release 必须重新显示为 `6.18.33.2-microsoft-standard-WSL2-x32off`。

## 相关脚本

- `operator-kit/scripts/build-custom-wsl-kernel.sh`：先校验固定的微软源码归档 SHA-256，再解压到全新 Ubuntu ext4 目录中构建；配置差异失败即停，默认 8 个并行任务，上限 12；完成时生成包含实际 jobs、用户、时间和直接构建产物哈希的 `build-stage-receipt.json`。
- `operator-kit/scripts/finalize-custom-wsl-kernel.ps1`：复核 build-stage receipt；从已校验归档中把微软模块生成器重新提取到 `/root` 隔离目录，验证生成器自身 SHA-256 且拒绝符号链接后才以 root 执行；随后清理 loop/scratch、执行 `qemu-img check`，并生成启用脚本要求的完整 manifest。
- `operator-kit/scripts/enable-custom-wsl-kernel.ps1`：校验产物和哈希、建立回滚状态、原子写入 `.wslconfig`。
- `operator-kit/scripts/rollback-wsl-kernel.ps1`：恢复原始配置并验证微软默认 release。
- `operator-kit/scripts/rollback-wsl-kernel.cmd`：双击的一键入口。

临时 Ubuntu 密码未写入脚本、清单或文档。

## 从固定源码重新构建的完整顺序

在确认固定版本的 source、build、modules 和 artifact 目标均不存在后，执行：

```powershell
wsl.exe -d Ubuntu-24.04 -u xhw -- bash /mnt/d/codework/websitebench-pipeline/operator-kit/scripts/build-custom-wsl-kernel.sh
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\operator-kit\scripts\finalize-custom-wsl-kernel.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\operator-kit\scripts\enable-custom-wsl-kernel.ps1
wsl.exe -d Ubuntu-24.04 -u xhw -- uname -r
```

构建脚本拒绝复用已有源码树，避免在无法确认修改历史的目录上生成系统级内核。任何旧目录或产物都只能在核对绝对路径、确认其为可再生成内容或完成归档后再清理；脚本本身不会递归覆盖。

启用事务的 rollback state 使用同目录临时文件和原子 replace 更新，并记录 `prepared`/`active` 阶段。若进程在 `.wslconfig` 激活前中断，一键回滚会验证并归档 staged 配置后终止未激活事务；如果状态 JSON 已损坏，脚本不会猜测，而会输出只针对已知 WebsiteBench override 的人工恢复步骤。
