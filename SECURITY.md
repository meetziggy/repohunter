# Security Policy

## Reporting a vulnerability
Please **do not** open a public issue for security problems. Instead, use GitHub's
**private vulnerability reporting** on this repository (Security → *Report a vulnerability*).

We'll acknowledge within a few days and keep you updated through the fix. Responsible
disclosure is appreciated and credited (with your permission).

## Scope
RepoHunter runs **locally** and evaluates third-party repositories. It plans; it never installs or
executes code on its own. Areas we care most about:
- Command/argument handling in the CLI and the local server
- Any path where repo metadata or an LLM response could influence a shell command or a write
- Handling of API keys read from your environment/config (they must never be logged or transmitted)

## Supported versions
Pre-1.0: only the latest `main` is supported. Update before reporting.
