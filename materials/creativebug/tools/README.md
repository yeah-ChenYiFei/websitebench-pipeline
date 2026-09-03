# creativebug 站点专属工具

这些脚本是 **creativebug 专用** 的（路径写死 `materials/creativebug`），
按「一个 PR 只修改一个网站 / 共享 Pipeline 改动走 main」的约定，
放在站点目录下，不进仓库根的共享 `tools/`。

| 脚本 | 用途 |
|---|---|
| `build_pages.py` | 由抓取件构建出货页（脚本剥离、资产本地化、外链中和、链接改投、边界页） |
| `gen_class_thumbnails.py` | 生成 `clone/static/class-thumbnails.json`（路由→缩略图，改投卡片换图用） |
| `shoot_candidate.py` / `compare_visual.py` | 拍候选帧 / 与参照帧比对出相似度 |
| `precheck.py` / `purge_pii.py` / `mutation_check.py` | 交付预检、PII 清除、检查器自检 |
| `ui_audit*.py` / `browser_loop.py` / `probe_browser.py` | 浏览器审计 |
| 其余 | 抓取、合并、清单生成等构建期脚本 |

**未提交**：`scrub-rules.json` —— 它含采集者真实邮箱，属 PII，按仓库规则不入库。
构建时需自行提供同名文件（`[{"find": "<真实值>", "replace": "<替换值>"}]`）。
