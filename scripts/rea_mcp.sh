#!/usr/bin/env bash
# Launches the REA MCP server (rea-agents, MIT) for agent sessions.
# Research/tooling only: never touches strategy, risk or execution.
# stdout is the MCP stdio channel, so every diagnostic goes to stderr.
set -euo pipefail

REA_VERSION="6.8.0"
NODE_MAJOR="24"

node_supported() {
  command -v node >/dev/null 2>&1 || return 1
  node -e '
    const [a, b, c] = process.versions.node.split(".").map(Number);
    const ok = (a === 22 && (b > 23 || (b === 23 && c >= 4)))
      || (a === 24 && (b > 22 || (b === 22 && c >= 1)))
      || (a === 26 && (b > 12 || (b === 12 && c >= 1)))
      || a > 26;
    process.exit(ok ? 0 : 1);
  '
}

if ! node_supported; then
  NVM_DIR="${NVM_DIR:-/opt/nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    export NVM_DIR
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh" >&2
    nvm install "$NODE_MAJOR" >&2
    nvm use "$NODE_MAJOR" >&2
  fi
fi

if ! node_supported; then
  echo "rea_mcp: Node.js ^22.23.4, ^24.22.1 or >=26.12.1 is required." >&2
  exit 1
fi

exec npx --yes "rea-agents@${REA_VERSION}" mcp
