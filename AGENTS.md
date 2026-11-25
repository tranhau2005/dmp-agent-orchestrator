# DriverManagementPlatform Agent Orchestrator contributor guidance

Agent orchestration, workflows, and tools for DriverManagementPlatform.

### Orchestration conventions

- Keep workflow coordination and tool adapters here; use controlled APIs/events for business operations.
- Do not bypass dmp-api authorization or access its database directly. Keep secrets out of logs and artifacts.

Coordinate API, event, and schema changes with [dmp-docs](https://github.com/tranhau2005/dmp-docs) and affected sibling repositories. Keep secrets, local environment files, generated data, and real personal data out of commits.

## Agent roles (Orca)

Development is orchestrated through Orca with three roles. Each role stays in its lane: the master does not edit product code, the worker does not merge, and the reviewer does not implement.

| Role | Agent | Model | Skills |
| --- | --- | --- | --- |
| Master (orchestrator) | Claude (`claude`) | `claude-opus-5-5` | `ak-brainstorm`, `ak-plan` |
| Worker | Codex (`codex`) | `gpt-6.1-terra`, effort `xhigh` | `ak-cook`, `ak-test` |
| Reviewer and merger | OpenCode (`opencode`) | `opencode-go/deepseek-v4.1-flash` | `ak-review-pr` |

All three run in auto mode, without per-command permission prompts. Enable it in Orca desktop Settings > Agents. This repository does not commit permission-bypass configuration. Do not switch agent or model on quota or access errors; report the exact error and wait for a decision.

### Delivery flow

1. **Master** runs `ak-brainstorm` to lock the outcome, constraints, non-goals, and acceptance criteria, then `ak-plan` to write a phased plan in `plans/`.
2. **Master** creates a worktree on a branch named `<type>/<short-kebab-description>` and dispatches a Codex worker with the plan path.
3. **Worker** implements with `ak-cook`, verifies with `ak-test`, commits, pushes, opens a pull request against `main`, and reports the PR URL.
4. **Master** dispatches the OpenCode reviewer on the same worktree with the PR number.
5. **Reviewer** reviews the PR with `ak-review-pr` and posts the findings on the PR. If anything blocks the merge, it does not merge and reports the findings; the master dispatches a Codex worker to fix them and then the reviewer again.
6. **Reviewer** merges when the merge conditions below hold, and reports the merge commit.

### Merge conditions

The owner authorizes the OpenCode reviewer, and only the reviewer, to merge a pull request into `main` when all of these hold:

- The review found no blocking issue (bug, regression, security problem, missing test for changed behavior, or violation of this file).
- Every CI check on the PR has passed (`gh pr checks <number> --watch` exits 0), or the repository has no CI checks.
- The PR is mergeable without conflicts and its branch follows the naming convention.

Merge with `gh pr merge <number> --merge`. The PR author and reviewer share one GitHub account, so post the review with `gh pr review <number> --comment` (GitHub rejects approving your own PR). Never force-push, bypass branch protection, deploy, or publish a release; those still need explicit owner approval.

### Commands

Dispatch a worker from the master, using an existing worktree (`current` or `path:<worktree>`):

```sh
orca orchestration worker-start --worktree current \
  --agent codex --model gpt-6.1-terra --effort xhigh \
  --task-title "<short title>" \
  --spec "Implement plans/<plan-dir>/plan.md with ak-cook, verify with ak-test, then commit, push, and open a PR against main. Report the PR URL."
```

When the worker reports the PR, dispatch the reviewer on the same worktree. OpenCode takes `--model` but not `--effort`, and needs an existing worktree:

```sh
orca orchestration worker-start --worktree current \
  --agent opencode --model opencode-go/deepseek-v4.1-flash \
  --task-title "review PR #<number>" \
  --spec "Review PR #<number> with ak-review-pr and post the findings with gh pr review --comment. Merge it with gh pr merge --merge only if the merge conditions in AGENTS.md hold; otherwise report the blocking findings with file:line and do not merge. Do not edit files."
```

To dispatch into another repository registered in Orca (`orca repo list`), create a worktree with a conventional branch, then start the worker on that path. Do not use `--worktree new-top-level`; it picks a branch name outside the convention.

```sh
orca worktree create --repo name:dmp-web --name feat-driver-search \
  --branch feat/driver-search --base-branch origin/main --json
orca orchestration worker-start \
  --worktree path:/home/haukun/orca/workspaces/dmp-web/feat-driver-search \
  --agent codex --model gpt-6.1-terra --effort xhigh \
  --task-title "driver search UI" \
  --spec "<task, owned files, acceptance criteria, checks to run>"
```

The worker follows that repository's `AGENTS.md`. For work that spans repositories, start one worker per repository, state the shared API, event, or schema contract in each spec, and pass `--deps '["<task_id>"]'` when a worker needs another worker's result first.

## Skill workflow (Codex)

- Implement accepted plans and scoped tasks with the `ak-cook` skill, following the plan's phases and acceptance criteria.
- Verify with the `ak-test` skill before reporting done: run this repository's checks, add or update tests for the changed behavior, and report the actual results.
- Finish by committing, pushing the branch, and opening a pull request against `main`. Do not merge it; the OpenCode reviewer reviews and merges.

## Skill workflow (OpenCode reviewer)

- Review the pull request with the `ak-review-pr` skill against this file, the plan's acceptance criteria, and the diff against `origin/main`.
- Post findings on the PR with file:line references, then merge or stop according to the [merge conditions](#merge-conditions). Do not edit files.
