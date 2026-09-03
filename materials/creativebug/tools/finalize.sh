#!/usr/bin/env bash
# 资产到齐后的收口流水线。一条命令跑完，每步失败即停 —— 中途绿灯不算数。
set -uo pipefail
cd "$(dirname "$0")/.."
source /home/user/alive/env.sh
W="$(pwd)"; SITE="$W/materials/creativebug"
step() { echo; echo "=== $* ==="; }
die() { echo "!! 失败于: $*"; exit 1; }

ZIP="${1:-$(ls -t incoming/cb-upload-*.zip 2>/dev/null | head -1)}"
[ -n "$ZIP" ] || die "没有找到资产包"

step "1/9 解包并 scrub"
unzip -oq "$ZIP" -d incoming/ || die 解包
python tools/scrub.py incoming/ | tail -1
# PII 模式从 tools/scrub-rules.json 读，不写死在脚本里 ——
# 这个文件本身不入库（.gitignore），把采集者真实标识硬编码在检查脚本里
# 等于让"防泄漏的检查"自己变成泄漏源。
[ -f tools/scrub-rules.json ] || die "缺 tools/scrub-rules.json，无法做 PII 扫描"
pat=$(python3 -c "import json,re;print('|'.join(re.escape(r['find']) for r in json.load(open('tools/scrub-rules.json'))))")
n=$(grep -ralE "$pat" incoming/ 2>/dev/null | wc -l)
[ "$n" = 0 ] || die "凭据/PII 扫描命中 $n"

step "2/9 合并资产（shutil.copy2，两份物理副本）"
python tools/merge_assets.py || die 合并

step "2b/9 CSS 本地化（必须在合并之后、清单之前）"
python tools/localize_css.py || die "CSS 本地化"

step "3/9 重新生成资产清单"
python tools/gen_manifest.py || die 清单

step "4/9 全量重建（新前缀生效，图片引用改指本地）"
rm -rf "$SITE/clone/frontend"
python tools/build_pages.py | grep -E 'pages_built|recovery_pages|asset_rewritten' || die 构建

step "5/9 precheck"
python tools/precheck.py || die "precheck 有阻断项"

step "6/9 起站 + 重拍候选帧（配方与参照帧一致）"
for pid in $(pgrep -f 'python app\.py' 2>/dev/null); do
  readlink /proc/$pid/cwd 2>/dev/null | grep -q creativebug && kill "$pid" 2>/dev/null
done
sleep 1
( cd "$SITE/clone" && rm -rf ../data && mkdir -p ../data && \
  PORT=9120 WEBSITEBENCH_SMTP_HOST=127.0.0.1 WEBSITEBENCH_SMTP_PORT=1025 \
  WEBSITEBENCH_SMTP_FROM=no-reply@creativebug.clone.test \
  setsid nohup python app.py > /tmp/cb-server.log 2>&1 < /dev/null & )
for _ in $(seq 40); do
  curl -sS -o /dev/null http://127.0.0.1:9120/healthz 2>/dev/null && break; sleep 0.5
done
rm -rf artifacts/candidate
python tools/shoot_candidate.py | tail -2 || die 候选帧

step "7/9 像素相似度（阈值 0.94，写回 visual_contract）"
python tools/compare_visual.py --reference incoming/cb-out/reference \
       --candidate artifacts/candidate --write-contracts
echo "（未达标不阻断收口 —— 读数如实记进 OPEN-DEFECTS，不粉饰）"

step "7b/9 清除交付库中的真实身份"
# 交付库与本地跑的是同一个文件：人用真实邮箱试一次注册就会落进交付物。
python tools/purge_pii.py || die PII 清除未干净

step "8/9 verify + 全套测试"
websitebench-offline-clone verify --site "$SITE" --section static > /tmp/verify-final.json 2>&1
python -c "
import json;d=json.load(open('/tmp/verify-final.json'));s=d['sections']['static']
print(' complete:',s['execution']['complete'],'| findings:',len(s['findings']))
raise SystemExit(0 if s['execution']['complete'] else 1)" || die "verify 未完成执行"
( cd "$SITE/clone" && python -m pytest tests -q 2>&1 | tail -2 ) || die 测试

step "9/9 交付自检 + cp -r 新路径复跑"
bash tools/delivery_check.sh || die 交付自检

echo; echo "=== 收口完成 ==="
