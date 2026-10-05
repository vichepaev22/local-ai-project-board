# Decisions

- 2026-10-05: Create a standalone clean sibling repository, not publish the private
  working directory. Copy an explicit code/assets/tests allowlist. Keep private data
  and running board intact; empty initialization replaces seeded personal projects.
- 2026-10-05: Keep Python standard library + vanilla JS; Python 3.11 minimum.
  Node is only needed for frontend tests, not using the board. MIT license permits reuse.
- 2026-10-05: User specifically requested automatic Hermes execution, replacing the
  initial manual-only proposal for other harnesses. Ship manual/Codex/Hermes modes;
  no speculative adapters. Hermes local CLI capabilities and official CLI/security
  documentation are the integration evidence. No `-z` auto-approval mode or `--yolo`.
- 2026-10-05: Manual by default; choosing a harness and confirming queued requests
  are separate actions. Hermes has the user's configured filesystem/tools/provider
  access, not an application sandbox. Warn before dispatch; never invent account limits.
- 2026-10-05: Public publication is authorized by the user's request that everyone
  can fetch and run the project. Only sanitized source/docs/tests are published.
  No private history migration and no automatic dispatch as part of publication.
- 2026-10-05: Use normal piped `hermes chat` without the optional chat `--oneshot`.
  Stream-json/non-TTY already completes one query. This also avoids confusing the
  safe chat boolean with Hermes's separate top-level auto-approval `-z` command.
- 2026-10-05: New project routes update only pending/active non-archived requests;
  completed, failed, interrupted and archived results retain their original route.
  Manual copying leaves requests queued: copying is not evidence of completion.
- 2026-10-05: Hermes child environment forces UTF-8 for Python-backed stdin/JSONL;
  no global locale/configuration changes. Local HTTP binding does not need reverse
  DNS and must remain usable when name resolution is slow or unavailable.
