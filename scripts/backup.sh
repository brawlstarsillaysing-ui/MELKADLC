#!/bin/sh
set -eu
umask 077
mkdir -p backups
# A consistent database snapshot. Retention and off-host encryption are operator responsibilities.
docker compose exec -T postgres pg_dump -U melka -d melka -Fc > "backups/melka-$(date -u +%Y%m%dT%H%M%SZ).dump"
