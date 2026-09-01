#!/usr/bin/env sh
set -eu

cd /data/projects/forestbridge-relay
umask 077
mkdir -p data caddy-data caddy-config

if [ ! -f .env ]; then
  ui_token="$(openssl rand -hex 24)"
  robot_token="$(openssl rand -hex 32)"
  {
    printf 'FORESTBRIDGE_UI_TOKEN=%s\n' "$ui_token"
    printf 'FORESTBRIDGE_ROBOT_TOKEN=%s\n' "$robot_token"
  } > .env
fi

docker compose config --quiet
docker compose up -d --build
docker compose ps
