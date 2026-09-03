#!/usr/bin/env bash
# 启动 clone。邮件环境变量必须在这里，不能靠人记得手动 export ——
# 少了它们服务器会静默进入 LOCAL_ONLY，注册链路直接失效。
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-9120}"
export WEBSITEBENCH_SMTP_HOST="${WEBSITEBENCH_SMTP_HOST:-127.0.0.1}"
export WEBSITEBENCH_SMTP_PORT="${WEBSITEBENCH_SMTP_PORT:-1025}"
export WEBSITEBENCH_SMTP_FROM="${WEBSITEBENCH_SMTP_FROM:-no-reply@clone.test}"
exec python app.py
