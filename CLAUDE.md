# DriverManagementPlatform Agent Orchestrator

Agent orchestration, workflows, and tools for DriverManagementPlatform.

## Repository map and collaboration

See [dmp-docs](https://github.com/tranhau2005/dmp-docs) for Kiro specifications, architecture, schema, and shared contracts. Coordinate interface changes with the sibling repositories: dmp-api, dmp-event-consumer, dmp-docs. Treat this repository as independently versioned and keep cross-repository changes explicit.

### Orchestration conventions

- Keep workflow coordination and tool adapters here; use controlled APIs/events for business operations.
- Do not bypass dmp-api authorization or access its database directly. Keep secrets out of logs and artifacts.

## Commit and branch conventions

- Commits MUST follow Conventional Commits 1.0: `<type>(<optional scope>)!: <description>`. Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. Use an imperative, lowercase description with no trailing period; keep the header at 72 characters or fewer. A body/footer is optional; mark breaking changes with `!` or a `BREAKING CHANGE:` footer.
- Branches MUST follow `<type>/<short-kebab-description>`, using one of the same types (for example `feat/m2-schema-migrations`, `fix/auth-token-expiry`, `docs/update-readme`). Never commit directly to `main`; work through pull requests.

## Agent roles (Orca)

The orchestrator session runs `claude-opus-5-5`. Dispatch implementation and review to Codex workers (`--agent codex --model gpt-6.1-terra --effort xhigh`), including workers in sibling repositories; all three run in auto mode. Commands and rules are in [AGENTS.md](AGENTS.md#agent-roles-orca). Auto mode does not grant permission to merge, deploy, or publish.
