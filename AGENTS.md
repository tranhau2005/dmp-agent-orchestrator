# DriverManagementPlatform Agent Orchestrator contributor guidance

Agent orchestration, workflows, and tools for DriverManagementPlatform.

### Orchestration conventions

- Keep workflow coordination and tool adapters here; use controlled APIs/events for business operations.
- Do not bypass dmp-api authorization or access its database directly. Keep secrets out of logs and artifacts.

Coordinate API, event, and schema changes with [dmp-docs](https://github.com/tranhau2005/dmp-docs) and affected sibling repositories. Keep secrets, local environment files, generated data, and real personal data out of commits.
