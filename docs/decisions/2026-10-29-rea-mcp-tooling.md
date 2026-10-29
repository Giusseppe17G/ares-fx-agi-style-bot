# REA MCP server for agent sessions

Date: 2026-10-29. Touches: agent tooling only. No strategy, risk, execution,
Expert, observability or backtesting behaviour changes.

## Context

The repository owner asked for REA ("Reverse Engineer Anything",
<https://github.com/morluto/rea>, npm package `rea-agents`) to be available to
agent sessions. REA is an MCP server and CLI that inspects native binaries,
JavaScript/Electron apps, .NET assemblies and websites locally.

## Decision

- `.mcp.json` registers a project-scoped MCP server `rea` that runs
  `scripts/rea_mcp.sh`.
- `scripts/rea_mcp.sh` pins `rea-agents@6.8.0` and launches it with
  `npx --yes`. REA requires Node.js `^22.23.4 || ^24.22.1 || >=26.12.1`; when the
  active Node is older and nvm is present, the script installs and selects
  Node 24 first. All diagnostics go to stderr because stdout is the MCP channel.
  Without a supported Node the script exits non-zero instead of starting.
- No Python or MQL5 dependency is added; nothing in `src/`, `config/` or `tests/`
  imports or calls REA.

Dependency justification (AGENTS.md rule 9): MIT licence, actively released
(release-please, versioned npm package), pinned to an exact version so an
upgrade is a reviewed change. Native analysis engines (Ghidra, IDA, Hopper,
Kuna) are optional and are not installed or configured here.

## Limits and rules of use

- AGENTS.md forbids copying proprietary code, protected trade names or private
  artefacts from third-party EAs. REA may be used to understand public
  behaviour and to inspect this project's own builds; its findings must not be
  turned into copied code, and any reconstruction must be an original
  implementation documented here.
- The first launch downloads the package from the npm registry; an offline
  session cannot start the server. Claude Code asks for approval before using
  a project-scoped MCP server.
- Runtime instrumentation through Frida needs its install script, which npm
  skips by default; this is intentionally left disabled.
