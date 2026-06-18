#!/bin/sh
set -eu

mkdir -p /app/data/artifacts/qr

# Render secret file: mount agent_config.yaml and point AGENT_CONFIG_PATH at it.
if [ -n "${AGENT_CONFIG_PATH:-}" ] && [ -f "$AGENT_CONFIG_PATH" ]; then
  cp "$AGENT_CONFIG_PATH" /app/agent_config.yaml
elif [ ! -f /app/agent_config.yaml ]; then
  if [ -f /etc/secrets/agent_config.yaml ]; then
    cp /etc/secrets/agent_config.yaml /app/agent_config.yaml
  else
    echo "ERROR: agent_config.yaml not found." >&2
    echo "Upload it as a Render secret file or set AGENT_CONFIG_PATH." >&2
    exit 1
  fi
fi

exec "$@"
