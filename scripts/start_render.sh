
#!/bin/sh
set -eu

alembic upgrade head

python -m telegram_bot.main &

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-10000}" --no-access-log
