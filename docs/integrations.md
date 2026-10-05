# Harness integration contract

Manual is the safe default. Codex and Hermes must be installed/authenticated locally.
The board is not a credential broker or harness installer.

## Codex
The existing JSON-RPC app-server bridge reads model catalog/rate limits and creates
or resumes a project thread only on confirmed dispatch. Related requests for one
project share one turn. Explicit models must be available; conflicting choices fail.
When switching an explicit model, an unsupported inherited reasoning effort is
replaced by the selected model's advertised default, not silently sent unchanged.
Approval requests are not auto-approved; open the linked Codex thread when prompted.
App-server capabilities vary by version. `PORTFOLIO_CODEX_BIN` overrides discovery.

## Hermes
The adapter discovers `hermes` in PATH or `PROJECT_BOARD_HERMES_BIN`.
It launches the CLI without a shell, passing literal request text over stdin:

```text
hermes chat --query-file - --format stream-json
  --max-turns 20 --run-budget 300 --in <absolute-workspace> --no-restore-cwd
  [--resume <Hermes-session-id>] [-m <configured-model>] [--provider <provider>]
```

JSONL protocol: `system/init` carries `session_id`, `text`/tool events are
non-terminal, and `result` must carry exit_code=0, nonempty text, and a session ID.
The subprocess must also exit successfully. No raw provider stderr is stored as a
user error. A final answer means execution returned, **not** that changes are correct.
Review and test the result. Per-project locking prevents competing Hermes processes.
Timeout cleanup targets only the owned process tree, on a best-effort basis.
Deliberately detached tools/daemons may outlive it. Check external tool/provider
operations separately: killing a local process cannot roll back completed effects.
Persisted active jobs are interrupted on restart, not automatically resumed.

Hermes uses the user's config, memory, rules, tools, approvals, and credentials.
It is not sandboxed by this board. `single_query_mode` and existing allowlists remain
the user's responsibility; the adapter adds no bypass flags. CLI compatibility was
inspected on v0.21.3 / c62bd9f2. See
[CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands/)
and [security documentation](https://hermes-agent.nousresearch.com/docs/user-guide/security/).

Codex thread IDs and Hermes session IDs are never interchanged. Changing a project's
workspace should start a new route; older results remain history, not new work.
To support another harness, add a bounded adapter plus lifecycle/error tests instead
of accepting arbitrary shell templates from HTTP. Manual prompt copy works today.
