#!/usr/bin/env bash
# G0 侦查：只回答 FAST-CLONE §3 的六问，串行 + 限速，不压源站
set -uo pipefail
UA_DESK='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
UA_MOB='Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
B=https://www.creativebug.com
g(){ curl -sS -A "$1" -H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' \
       -H 'Accept-Language: en-US,en;q=0.9' --compressed --max-time 30 "${@:2}"; }

echo "== Q1/Q2 渲染方式与 UA 分叉 =="
g "$UA_DESK" -D recon/root.desk.hdr -o recon/root.desk.html "$B/"
g "$UA_MOB"  -D recon/root.mob.hdr  -o recon/root.mob.html  "$B/"
echo "desktop bytes: $(wc -c < recon/root.desk.html)   mobile bytes: $(wc -c < recon/root.mob.html)"

echo "== Q3 速率限制：20 次串行，每次间隔 0.4s =="
for i in $(seq 1 20); do
  printf '%s ' "$(curl -sS -o /dev/null -w '%{http_code}' -A "$UA_DESK" --max-time 20 "$B/")"
  sleep 0.4
done; echo

echo "== Q4 路由权威 =="
g "$UA_DESK" -o recon/robots.txt "$B/robots.txt"
for p in /sitemap.xml /sitemap_index.xml /sitemap-index.xml /sitemaps.xml; do
  printf '%s %s\n' "$(curl -sS -o /dev/null -w '%{http_code}/%{size_download}B' -A "$UA_DESK" --max-time 20 "$B$p")" "$p"
done

echo "== 首页出链（D0 闭合目标）=="
python3 - <<'PY'
import re,collections,urllib.parse as up
h=open('recon/root.desk.html',encoding='utf-8',errors='replace').read()
raw=re.findall(r'href\s*=\s*["\']([^"\']+)["\']',h)
paths=set()
for r in raw:
    u=up.urlparse(up.urljoin('https://www.creativebug.com/',r))
    if u.netloc.endswith('creativebug.com') and u.scheme in ('http','https'):
        paths.add(u.path.rstrip('/') or '/')
seg=collections.Counter(p.split('/')[1] if p!='/' else '(root)' for p in paths)
print('原始 href:',len(raw),' 站内唯一路由:',len(paths))
print('一级段分布:',dict(seg.most_common(25)))
open('recon/home-outlinks.txt','w').write('\n'.join(sorted(paths))+'\n')
print('正文长度（去标签）:',len(re.sub(r'<[^>]+>',' ',re.sub(r'(?is)<(script|style).*?</\1>',' ',h)).split().__len__().__str__()),'词')
PY
echo "== DONE =="
