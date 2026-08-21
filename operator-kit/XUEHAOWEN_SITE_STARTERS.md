# 薛皓文：5 个网站的新对话启动块

使用方法：每个网站新建一个 Codex 对话，以 `D:\codework\websitebench-pipeline` 为工作区，先粘贴 `operator-kit/NEW_SITE_PROMPT_TEMPLATE.zh-CN.md` 的完整模板，再追加对应代码块。以下英文轨迹来自用户提供的分配表原文，允许作为正式 `HUMAN_TRACE_TEXTS`；不得翻译或润色。它们只授权实现本地 clone，不授权在源站注册、评论、预约、订阅、下单、填写真实地址或付款。

## 16 — Bean Box

```text
ASSIGNMENT_ID=16
SITE_ID=bean-box
SOURCE_URL=https://beanbox.com
CATEGORY=recurring-order
EXPANDED_TASK_SHEET_KEY=WB016-T01..T23
HUMAN_TRACE_TEXTS=["[697] On Bean Box, select a monthly subscription plan (monthly curated coffee box), choose 6-cup size with ground coffee, and reach the checkout page with shipping and payment details filled in."]

安全补充：只在本地 clone 使用合成的收货和支付 fixture；不得在源站开始真实订阅、提交地址或支付信息。
```

## 17 — BeerAdvocate

```text
ASSIGNMENT_ID=17
SITE_ID=beeradvocate
SOURCE_URL=https://beeradvocate.com
CATEGORY=beer-review
EXPANDED_TASK_SHEET_KEY=WB017-T01..T23
HUMAN_TRACE_TEXTS=["[706] Submit a review for an Imperial Stout on BeerAdvocate with all dimension scores filled and exactly this comment: \"Rich malt, roasty aroma, full body.\""]

安全补充：评论写入只在本地 clone 验证；不得在源站创建账号或发布评论。
```

## 18 — BetterHelp

```text
ASSIGNMENT_ID=18
SITE_ID=betterhelp
SOURCE_URL=https://betterhelp.com
CATEGORY=health-medical
EXPANDED_TASK_SHEET_KEY=WB018-T01..T23
HUMAN_TRACE_TEXTS=["[35] Sign up on BetterHelp, book a counseling session, and complete the initial questionnaire"]

安全补充：只使用虚构身份和合成健康信息；不得在源站预约真实咨询、提交问卷或保存任何个人健康数据。
```

## 19 — Blinkist

```text
ASSIGNMENT_ID=19
SITE_ID=blinkist
SOURCE_URL=https://blinkist.com
CATEGORY=reading-self-study
EXPANDED_TASK_SHEET_KEY=WB019-T01..T23
HUMAN_TRACE_TEXTS=["[821] Register on Blinkist with email reader2026@example.com, subscribe to the Premium annual plan, then search for Atomic Habits and add it to My Library (favorites)"]

安全补充：分配表中的邮箱仅作为本地 clone 测试 fixture；不得在源站注册、订阅或付款。
```

## 20 — Bluemercury

```text
ASSIGNMENT_ID=20
SITE_ID=bluemercury
SOURCE_URL=https://bluemercury.com
CATEGORY=beauty-booking
EXPANDED_TASK_SHEET_KEY=WB020-T01..T23
HUMAN_TRACE_TEXTS=["[781] On the Bluemercury website, purchase a skincare product, add to cart, and proceed to checkout"]

安全补充：只在本地 clone 使用合成地址和 `local-sandbox` 支付；不得在源站提交订单或付款。
```

完整的 23 项扩展覆盖以 `operator-kit/assignments/xue-haowen.json` 为准。若目标站当前结构与历史任务不一致，应保留原始任务，并把当前不可访问或已下线的表面记录为 `unavailable`，不得伪造证据。
