#!/bin/sh
# Vérifie que `claude -p` headless renvoie une sortie structurée (sans outils).
set -e
SCHEMA='{"type":"object","properties":{"pong":{"type":"boolean"}},"required":["pong"]}'
printf '%s' "Réponds avec pong=true." | "${CLAUDE_BIN:-claude}" -p --output-format json \
  --json-schema "$SCHEMA" --tools "" --strict-mcp-config --setting-sources "" \
  --no-session-persistence --model "${CLAUDE_MODEL:-haiku}" \
  --system-prompt "Tu réponds uniquement via la sortie structurée."
echo
