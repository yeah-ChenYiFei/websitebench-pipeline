# 新增离线 Clone 的单站公共部署

当需要让一个新的离线 clone 可部署到受保护公网评审面时，使用本指南。每个站点
只能有自己的 Cloudflare Worker、custom domain、GitHub Actions dispatcher、
concurrency group 和 `site_id`；不得把新站加入站点数组、matrix 或批量发布入口。

本指南只使候选具备部署能力，不提供真实发布、版权、再分发、支付、邮件或技术
验证授权。真实动作仍需要当前任务明确授权。

## 支持范围和前置条件

当前 `deploy/generic-offline-clone/` 支持 Python/ASGI clone：容器入口以 Python
3.12 运行，并要求服务监听 `10000`、提供 `GET /healthz`。它从该站自己的
`backend/runtime.json` 派生 `site_id`、显示名称、`site.public_origin` 和部署
profile；v2 descriptor 再生成该站独立的 Worker 名称与 custom-domain route。

新站开始前：

1. 选择一个唯一、稳定、全小写连字符形式的 `<site-id>`。它对应
   `materials/<site-id>/`、`websitebench-<site-id>-demo`、
   `public-demo-<site-id>` 和一个独立 public origin。
2. 完成该站自己的 source scope、`clone.yaml`、当前 technical evidence 与
   candidate 测试。它们不能由其他站点的证据替代。
3. 若范围包含账户、密码恢复、邮件、订单、支付或数据库，先遵守
   [`websitebench-site-backend-mandate.md`](websitebench-site-backend-mandate.md)：
   scaffold 该站 backend，并让 `backend/runtime.json` 成为唯一运行合约。
4. 非 Python/ASGI runtime 不可伪装成 generic package。先增加并测试一个专用、
   站点隔离的 packaging adapter，再创建公网 dispatcher。

## 添加站点配置

从 `deploy/generic-offline-clone/deployment.v2.example.json` 创建
`deploy/generic-offline-clone/deployment.<site-id>.v2.json`。保持 v2 的六个顶层
字段，并至少满足：

```json
{
  "schema_version": "websitebench.generic-public-clone-deployment.v2",
  "source_dir": "materials/<site-id>/clone",
  "backend_runtime": "materials/<site-id>/backend/runtime.json",
  "deployment_profile": "cloudflare-review",
  "runtime": {
    "command": ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "10000"],
    "port": 10000,
    "health_path": "/healthz",
    "python_requirements": ["fastapi==<pinned-version>", "uvicorn==<pinned-version>"],
    "support_paths": []
  },
  "cloudflare": {
    "worker_name": "websitebench-<site-id>-demo",
    "compatibility_date": "<current-date>",
    "instance_type": "basic",
    "max_instances": 1
  }
}
```

`backend/runtime.json` 必须使用同一个 `site.id`，并以
`https://<site-id>.website-bench.com`（或已获批准的唯一 host）作为
`site.public_origin`。不要在 descriptor 再次维护 domain、数据库身份、邮件用途
或支付语义；这些都属于 runtime contract。Cloudflare review profile 的 SQLite 是
可重置的，不得宣称其持久化。

## 新建固定 dispatcher

创建 `.github/workflows/deploy-<site-id>-public.yml`。不要改动已有站点 wrapper，
不要创建一个接收 site 名称的通用 dispatcher。下面是 generic package 的完整结构；
只替换尖括号中的单站值：

```yaml
name: Deploy <Site label> public demo
on:
  push:
    branches: [web2code2web]
    paths: [".github/workflows/deploy-<site-id>-public.yml"]
  workflow_dispatch:
    inputs:
      deploy:
        description: "Publish the anonymous public demo"
        required: true
        type: boolean
        default: false
concurrency: { group: public-demo-<site-id>, cancel-in-progress: false }
jobs:
  deploy:
    if: github.event_name == 'workflow_dispatch'
    uses: ./.github/workflows/public-demo-site.yml
    with:
      site: <site-id>
      package: deploy/generic-offline-clone
      wrangler_config: deploy/generic-offline-clone/wrangler.generated.jsonc
      prepare_command: node deploy/generic-offline-clone/scripts/prepare.mjs --config deploy/generic-offline-clone/deployment.<site-id>.v2.json
      deploy_command: npx --prefix deploy/generic-offline-clone wrangler deploy --config deploy/generic-offline-clone/wrangler.generated.jsonc --containers-rollout=immediate
      url: https://<site-id>.website-bench.com
      deploy: ${{ inputs.deploy }}
    secrets: inherit
```

The push trigger merely registers `workflow_dispatch`; its job is skipped on
push. The wrapper exposes only `deploy`. A false value runs package tests,
candidate preparation and Wrangler dry-run; only true permits the Cloudflare
publish command. The shared workflow then binds public health to the new
build ID and checks anonymous `401`, authenticated access, `/__bench/` `404`
after authentication, and `noindex` edge headers.

The public dispatcher contract test discovers every file matching
`deploy-<site-id>-public.yml`. A correctly formed new wrapper needs no central
site-list edit: it is automatically checked for a fixed site, unique public URL,
unique concurrency group, no matrix, and no bulk-site input.

## 新建该站的 CI 门禁

创建 `.github/workflows/tests-<site-id>.yml`，与部署 dispatcher 同样一站一份。
它只把自己的 site 传给共享模板，并只在本站材料或共享代码变化时触发：

```yaml
name: tests (<site-id>)
on:
  push:
    paths:
      - materials/<site-id>/**
      - src/**
      - pyproject.toml
      - .github/workflows/clone-diagnostics.yml
      - .github/workflows/tests-<site-id>.yml
  pull_request:
    paths:
      - materials/<site-id>/**
      - src/**
      - pyproject.toml
      - .github/workflows/clone-diagnostics.yml
      - .github/workflows/tests-<site-id>.yml

jobs:
  baseline:
    uses: ./.github/workflows/clone-diagnostics.yml
    with:
      site: <site-id>
```

`tests/project/test_verification_workflows.py` 按 `materials/*/clone.yaml` 发现
站点，因此新站带上 `clone.yaml` 之后，缺失这份 dispatcher 会直接让该测试失败，
不需要再去任何中心清单里登记。退役站点时把这个文件与该站材料一起删除。

## Local preflight and review

Run these commands from the repository root before requesting a real publish:

```bash
cd deploy/generic-offline-clone
npm ci
npm test
node scripts/prepare.mjs --config deployment.<site-id>.v2.json --check-only
node scripts/deploy.mjs --config deployment.<site-id>.v2.json --dry-run
```

Also run the selected clone's test suite and its current baseline/strict
technical checks. Inspect generated `wrangler.generated.jsonc` only as a local
candidate artifact; it is regenerated per run and must not be reused as another
site's deployment identity.

After review, use only the new workflow's Actions **Run workflow** control:
first with `deploy=false`, then—with current scoped authority—with `deploy=true`.
Never dispatch a collection of sites. Do not put secrets, cookies, payment data
or sensitive form values in the descriptor, workflow inputs, reports or logs.

## Adding a non-generic adapter

When a clone cannot satisfy the generic Python/ASGI contract, first create a
tested site-specific deployment package. It must still expose the same wrapper
shape: exactly one fixed `site`, one unique HTTPS URL, one unique
`public-demo-<site-id>` lock, one `deploy` boolean and the reusable
`public-demo-site.yml` call. Preserve the shared candidate dry-run, Cloudflare
publish, build-bound health, Basic Auth and edge-header checks; do not bypass
them with a bespoke workflow.
