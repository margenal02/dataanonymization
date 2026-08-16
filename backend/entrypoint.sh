#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python -m anonymizer.uie_manager &
UIE_MANAGER_PID=$!

attempt=0
until curl -fsS http://127.0.0.1:8765/status >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if ! kill -0 "$UIE_MANAGER_PID" 2>/dev/null; then
        echo "UIE-base 模型管理进程启动失败。" >&2
        exit 1
    fi
    if [ "$attempt" -ge 30 ]; then
        echo "UIE-base 模型管理进程启动超时。" >&2
        exit 1
    fi
    sleep 1
done

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 3600 --access-logfile - --error-logfile -
