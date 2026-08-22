# Site 33（Coursera 离线克隆）本地验收清单

验收前请确保 Python 3.12（本机 repo 根目录已有 `.venv`，内置 fastapi/uvicorn）。

## 1. 启动

```bash
cd /home/alive/websitebench-pipeline
# 若 8899 已被占用，先停旧进程
# 启动（首次或改过 Python 代码后必须重启；静态文件/模板/CSS 改动热生效）
cd materials/33/clone
setsid nohup /home/alive/websitebench-pipeline/.venv/bin/python -m uvicorn app:app \
  --host 127.0.0.1 --port 8899 --log-level warning >/tmp/uv8899.log 2>&1 &
# 冒烟：curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8899/   -> 200
```

浏览器打开：**http://127.0.0.1:8899/**

## 2. 预置账号（DB 已复位时的种子状态）

| 账号 | 密码 | 状态 |
|---|---|---|
| `progress@coursera.test` | `Progress-Learner-33` | 已登录学习者，已报名 Deep Learning Specialization（audit/active） |
| `empty@coursera.test` | `Empty-Learner-33` | 空学习者（无报名） |
| 任意 `xxx@coursera.test` | 任意 ≥8 位密码 | 登录页未知邮箱+密码 = 自动注册并登录 |

快捷登录入口：`/auth/local-learner`、`/auth/learning-demo`（POST 表单）。

## 3. 逐项验收（对照"原网站有什么、这个地方就有"）

### A. 注册 / 登录（完全本地，无任何云服务）
1. `/signup` 填邮箱（`.test` 结尾）+ 姓名 + 密码 → 跳到本地收件箱 `/local-inbox?purpose=registration`
2. 收件箱显示 6 位验证码（仅本浏览器会话可见）→ 填回验证 → 进入引导页
3. 选身份+目标提交 → my-learning
4. 登出 → 用新账号重新登录成功；错误密码被拒（提示错误）
5. `/login` 对话框：先输邮箱 → 输密码 → 登录；「Continue with Google/Facebook/Apple」为占位入口

### B. 首页 / 浏览
6. 首页：顶部深色条 + 品牌栏；促销轮播可点左右箭头/圆点切换 4 张（Learn without limits / Save 40%… / Close team skill gaps… / Start, switch…）；"New and popular"、职业路径、合作院校、FAQ 等区块齐全
7. 页脚四栏（Coursera / Community / More / Mobile App）链接可点
8. `/browse`：分类 chips（11 类）→ 深色促销带（Get Coursera Plus / Save 30% today）→ Most popular → Explore roles（职业卡可点）→ Google Analytics / 项目管理 / AI 入门三个栏目 → Trending / In-demand skills / New releases / Leading partners / FAQ

### C. 搜索与筛选（前后端联动）
9. `/search?q=Deep+Learning`：顶部浅色 AI 摘要面板 + 4 张入门卡 + 追问 chips；左侧筛选栏（Topic/Duration/Learning Product/Language/Level/Status/AI skills），勾选任一即自动提交
10. 验证过滤：`level=Beginner` → 11 条；`level=Intermediate` → 1 条；`rating=4.8` → 2 条；`status=free-trial` → 1 条；`product=professional-certificates` → 11 条
11. 无结果：`/search?q=zzzz-no-match-websitebench` → "No results" 提示 + 返回链接
12. 卡片：点击整卡跳转（标题链接为真实 `<a>`），"Compare" 为界面元素

### D. 课程 / 专项
13. `/learn/neural-networks-deep-learning`：课程英雄区（Enroll for free）、统计条、About/Outcomes/Modules/Recommendations/Testimonials/Reviews 锚点、模块手风琴（含 "Module details"）、相关课程 4 卡、评价者 4 条、FAQ、促销带
14. `/specializations/deep-learning`：5 门课程列表（标题可点）、What you'll learn/Skills/Tools/Details、讲师卡、"Prepare for a career…"、FAQ（3 条 + More questions）
15. 匿名点 "Enroll for free" → 弹出登录对话框；登录后 → 报名表单

### E. 学习闭环（progress@coursera.test）
16. `/my-learning`：已报名课程卡 + "Continue learning"
17. 课程主页 `/learn/neural-networks-deep-learning/home/module/1`：周目标、目标切换、资源
18. 课时 `/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome`：课程内容 + 测验 + 书签/完成按钮
19. 测验：提交 `answer=Activation function` → 100 分；错误答案 → 0 分并提示
20. 进度/书签/我的记录页 200；`/account/preferences` 三个 tab（Communication / Notes / Calendar）可切换

### F. 结算与订单（local-sandbox，绝无真实付款）
21. 登录后从专项页 "Enroll for free"/付费入口 → `/checkout/deep-learning` → 支付页（演示卡号输入**无 name、不提交**）→ Review（CN¥0 today / ¥196 每月）→ 选 "Simulate approval" → 订单页
22. 订单详情 + `/my-purchases/transactions`；订单可取消（取消后报名同步 CANCELED）
23. 选 "Simulate decline" / "Simulate retry" → 安全失败页，不产生订单；非法 scenario → 拒绝

### G. 其他
24. 找回密码：`/account-recovery` 提交未知邮箱不泄露；已知邮箱 → 本地收件箱取码 → 新密码 → 登录
25. 404：访问任意不存在路径 → 品牌化恢复页（保留主导航 + browse/search 链接）
26. 帮助中心 `/help`：文章 + 反馈按钮（登录后可提交）；`/about/contact` 支持页
27. 语言：所有公共路由为纯英文（无中文残留）

## 4. 机器指标（诊断辅助，非验收门槛）

```bash
cd /home/alive/websitebench-pipeline
.venv/bin/python materials/33/clone/measure_structure_consistency.py   # 结构一致性：0.903
.venv/bin/python materials/33/clone/measure_visual_regions.py         # 像素 SSIM：0.750（动态内容受限）
.venv/bin/websitebench-offline-clone verify --site materials/33 --section static   # 87/87 clean
.venv/bin/websitebench-workflow check-payment-scope --proposal materials/33/scope/payment-scope.json  # passed
```

## 5. 验收中动了 DB 后复位（重要）

手工操作会写入 `materials/33/data/33.sqlite3`（订单、进度、改密码、取消报名等）。
验收结束后恢复到种子状态：

```bash
cd /home/alive/websitebench-pipeline
.venv/bin/python -c "import sys; sys.path.insert(0,'materials/33/clone'); from backend.learning_db import reset; reset()"
# 复验：progress@coursera.test 登录 303，my-learning 200，报名 audit/active
```

## 6. 常见问题

- **改了 Python（app.py/ui.py 等）没生效**：uvicorn 需重启（kill 8899 再启）；CSS/模板改动无需重启
- **页面 401/404**：多为未登录或报名状态被改（见第 5 节复位）
- **登录后看不到课程**：用 `progress@coursera.test` 或 `/auth/learning-demo`
- **端口冲突**：`ss -tlnp | grep 8899` 找出旧进程 kill 后再启
