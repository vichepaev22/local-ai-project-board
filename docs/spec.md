# Local AI Project Board — specification

## Goal and users
A public, reusable local planning board: clone it, run with Python, add a project
workspace, queue a request, explicitly send it to Codex or Hermes, inspect the
result. It can also be launched from any harness terminal in manual mode.
The existing private board and its data must remain unchanged.

## Acceptance
1. A fresh clone starts with `python run.py` (Python 3.11+, no pip packages).
   It initializes an empty board; repeated starts preserve existing data.
2. Manual is the default. Startup, reading state, planning, and archiving never
   execute a request. Requests can be copied for any other harness.
3. `--bridge codex` uses the locally installed authenticated Codex app-server.
   `--bridge hermes` uses a configured Hermes CLI automatically after confirmation.
   Missing harness/auth/provider is an explicit failure, never fake completion.
4. A project has an explicit existing absolute workspace before automatic execution.
   No implicit parent directory or private preconfigured project/thread is shipped.
5. Hermes accepts a literal prompt without shell interpretation, returns terminal
   result/error, has a timeout, serializes work in the same project, and does not
   enable `--yolo`, accept hooks, alter credentials, or claim a Codex sandbox.
6. Runtime data, logs, prompts/results, account information, private paths, and
   secrets are absent from Git. HTTP serves only UI assets, binds loopback, checks
   Host and write Origin/JSON content type. Not a multi-user/authenticated service.
7. Public documentation explains install/start/stop, both integrations, local data,
   permissions, compatibility limits, license, and development checks.
8. Python/Node deterministic tests pass; independent review precedes public push.
   Verify fresh-clone startup and public repository/commit after publication.

## Non-goals
No deployment, cloud hosting, auto-dispatch on startup, scheduled work, arbitrary
command templates, provider keys in board settings, paid-provider configuration,
universal automatic integration, or exporting private board history.
CI checks supported OSs; local testing alone does not prove other OSs or providers.

## Interfaces
Bridge instances expose `kind`, `online`, `snapshot()`, `available_models()`,
`current_budget()`, `schedule_reconciliation(queue)`, `dispatch_many(queue_ids)`.
Non-Codex budget has `limitEnforced:false`, `dispatchAllowed:bool`, unknown
percentages (null), `isLive:false`; no invented provider limits. Default absent
`limitEnforced` remains true for legacy Codex tests. Snapshot includes kind/message.
Hermes module uses lazy `import server` inside callbacks to avoid a circular import.
Runtime data helper: `initialize_data(Path) -> dict[str, Path]` with DATA and
PROJECTS_FILE/BUDGET_FILE/QUEUE_FILE/ACTIVITY_FILE/EVENTS_FILE/TOMORROW_FILE/BOARD_FILE.
Env: PROJECT_BOARD_BRIDGE (manual/codex/hermes), PROJECT_BOARD_DATA_DIR.
CLI: run.py --bridge --port --data-dir [--open] [--background]. Default port 5137.
Workspace operations: add-project `workspace` optional; set-workspace
`projectId`, `workspace`, `revision`. Empty allowed for planning, never execution.
Hermes routes carry harness=hermes/sessionId; Codex routes harness=codex/threadId.
Each harness ignores the other's identifiers. Persistence stays in existing JSON API.

## Verification boundaries
Fake transport/subprocess tests prove routing and lifecycle without spending tokens.
A synthetic real Hermes run is separately reported (no user workspace/provider edits).
Timeout/provider failure must not be represented as end-to-end success.
