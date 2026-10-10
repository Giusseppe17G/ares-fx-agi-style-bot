# Documentation lint in CI

Date: 2026-10-10. Touches: observability/tooling only. No strategy, risk,
execution, Expert or production Python behaviour changes.

## Context

`PROJECT_SPEC.md` §16 left "lint documental" pending after the Python CI
workflow. Documentation here is part of the audit trail: ADRs, evidence READMEs
and the spec name scripts, fixtures and evidence files by path, and AGENTS.md
rule 10 forbids secrets, real account IDs and personal data in the repository.
Nothing checked that those paths still exist or that a session path or token
had not leaked into a document.

## Decision

`scripts/check_docs.py` (`docs_lint_v1`), stdlib only, runs in
`.github/workflows/validation.yml` before the native and pytest steps:

- Scope: Markdown files in the git index of the repository root. Untracked
  files are invisible, so a document cannot point at a file that was never
  committed. Not a git repository root, no git or no tracked files is an error
  (exit 2), never a pass.
- Each document must decode (UTF-8, or UTF-16 with a BOM, as `README.md`) and
  close its code fences.
- Relative links (inline, image and reference) and backticked paths whose first
  component is a tracked top-level directory must resolve to a tracked file or
  directory. Fenced code and code spans are not links. `data/` is skipped: it is
  the runtime state root, whose logs, reports and databases are gitignored, and
  package-relative names such as `data/indicators.py` collide with it.
  Placeholders, globs and commands with spaces are prose.
- Everywhere, including fenced code: home directories of real users
  (`/home/<x>`, `/Users/<x>`, `C:\Users\<x>`; `user`, `Administrator`,
  `runner` and `<placeholders>` are generic), the root account home, session
  scratch paths, token-shaped values (Telegram bot, GitHub, AWS, Slack, API
  keys, private key blocks) and email addresses outside example domains.
  Secret and email findings name the pattern, never the value.

## Limits

Pattern checks cannot prove the absence of secrets or account IDs; they catch
known shapes. Package-relative paths are not resolved. The lint does not judge
prose, spelling or whether a document is current.
