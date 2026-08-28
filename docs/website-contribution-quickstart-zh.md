# WebsiteBench 网站 PR 简明说明

仓库：<https://github.com/780078268/websitebench-pipeline>

## 分配前

维护者先在 `sites/status.tsv` 查网站：

- `final`：直接修改已有 `sites/<site-id>`。
- 有 `Pipeline_PR`、未 final：复用该 PR 的 review 快照，不要重复提交。
- `no-pr`、未 final：从 planned 空分支开始开发。

分配网站不会让贡献者成为维护者；Review、合并和 final 状态仍由仓库维护者负责。

## 开发和提 PR

以 `notion` 为例，先 Fork 仓库，再只下载一个网站：

```bash
git clone --single-branch --branch sites/notion --depth=1 \
  --filter=blob:none \
  https://github.com/780078268/websitebench-pipeline.git \
  websitebench-notion

cd websitebench-notion
git remote add fork https://github.com/YOUR_GITHUB_NAME/websitebench-pipeline.git
git switch -c fix/notion-xxx
```

修改完成后：

```bash
git add .
git commit -m "fix(notion): 简要说明"
git push -u fork HEAD
```

创建 PR 时必须选择：

```text
base：sites/notion
head：个人 Fork 的修改分支
```

把 `notion` 换成实际 site id。网站 PR 不要提交到 `main`。

## 注意

- 一个 PR 只修改一个网站。
- 不要使用全量 clone、`git fetch --all` 或 `git pull --all`。
- 不要提交 Cookie、Token、密码、`.env`、登录数据或真实用户数据。
- 提交前运行该网站的本地测试，并写明结果和已知问题。
- 不用修改 WcodeW；网站确认 final 后由维护者统一同步。
