#!/usr/bin/env bash
# §第一原则 7 + §11：交付目录自检 + cp -r 到全新路径复跑。
# 不打包，所以这三条自检必须挂在目录上——过去是打包过滤器替我们挡的。
set -uo pipefail
SITE="$(cd "$(dirname "$0")/.." && pwd)/materials/creativebug"
FRESH="${1:-/tmp/cb-delivery-$$}"

# 跑过 pytest 就会重新生成 __pycache__。交付前清一次是流程的一部分，
# 不是"上次清过就永远干净"。
find "$SITE" \( -name __pycache__ -o -name .pytest_cache \) -type d -exec rm -rf {} + 2>/dev/null

echo "=== 交付目录自检（工作树）==="
fail=0
chk() { printf '  %-42s %s\n' "$1" "$2"; [ "$3" = 0 ] || fail=1; }

n=$(find "$SITE" \( -name creds.env -o -name 'storage_state*' \) 2>/dev/null | wc -l)
chk "凭据文件" "$n（须 0）" "$n"
n=$(find "$SITE" \( -name __pycache__ -o -name .pytest_cache \) 2>/dev/null | wc -l)
chk "工具缓存目录" "$n（须 0）" "$n"
n=$(find "$SITE" -path '*/run/*' 2>/dev/null | wc -l)
chk "run/ 残留" "$n（须 0）" "$n"
n=$(find "$SITE" \( -name dist -o -name '*.tar.gz' -o -name SHA256SUMS \) 2>/dev/null | wc -l)
chk "打包产物（§第一原则 7 不打包）" "$n（须 0）" "$n"
n=$(find "$SITE" -type f -links +1 2>/dev/null | wc -l)
chk "硬链接 st_nlink>1（红线 3）" "$n（须 0）" "$n"

# 凭据字节流扫描：扫的是要交付的字节，含缓存目录
if [ -f "$(dirname "$0")/scrub-rules.json" ]; then
  pats=$(python3 -c "import json,sys;print('|'.join(r['find'] for r in json.load(open(sys.argv[1]))))" \
         "$(dirname "$0")/scrub-rules.json")
  n=$(grep -ralE "$pats" "$SITE" 2>/dev/null | wc -l)
  chk "凭据/PII 字节流扫描" "$n 命中（须 0）" "$n"
else
  chk "凭据/PII 字节流扫描" "跳过：无 scrub-rules.json —— 这是缺口不是通过" 1
fi

echo
echo "=== cp -r 到全新路径（不是 cp -al）==="
rm -rf "$FRESH"; mkdir -p "$FRESH"
cp -r "$SITE" "$FRESH/"
echo "  目标: $FRESH/creativebug  ($(du -sh "$FRESH/creativebug" | cut -f1))"
n=$(find "$FRESH" -type f -links +1 2>/dev/null | wc -l)
chk "副本硬链接" "$n（须 0）" "$n"
n=$(find "$FRESH" \( -name __pycache__ -o -name .pytest_cache \) 2>/dev/null | wc -l)
chk "副本工具缓存" "$n（须 0）" "$n"

echo
echo "=== 新路径起站 ==="
PORT=$((9130 + RANDOM % 20))
( cd "$FRESH/creativebug/clone" && rm -rf ../data && mkdir -p ../data && \
  PORT=$PORT WEBSITEBENCH_SMTP_HOST=127.0.0.1 WEBSITEBENCH_SMTP_PORT=1025 \
  WEBSITEBENCH_SMTP_FROM=no-reply@creativebug.clone.test \
  setsid nohup python app.py > /tmp/cb-fresh-$PORT.log 2>&1 < /dev/null & )
for _ in $(seq 40); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz" 2>/dev/null)
  [ "$code" = 200 ] && break
  sleep 0.5
done
chk "/healthz" "$code" "$([ "$code" = 200 ] && echo 0 || echo 1)"
for r in / /classes /site/about; do
  c=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$r")
  chk "GET $r" "$c" "$([ "$c" = 200 ] && echo 0 || echo 1)"
done

echo
echo "=== 新路径跑测试（§11 要的第二个数字）==="
( cd "$FRESH/creativebug/clone" && timeout 1200 python -m pytest tests -q 2>&1 | tail -3 )

for pid in $(pgrep -f "python app.py" 2>/dev/null); do
  readlink /proc/$pid/cwd 2>/dev/null | grep -q "$FRESH" && kill "$pid" 2>/dev/null
done
echo
echo "自检结论: $([ $fail = 0 ] && echo '全过' || echo '有未过项')"
exit $fail
