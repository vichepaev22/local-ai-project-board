# Working on this repository

- Goal: a reusable local-first board with optional Codex/Hermes execution.
- Python 3.11+ standard library only; vanilla JS. Do not add dependencies casually.
- Read README.md and docs/spec.md before substantive changes. Preserve docs/decisions.md.
- Run `python -m unittest discover -s tests -p "test_*.py"` and
  `node --test tests/*.test.cjs` with temporary fixtures; never dispatch real project tasks in tests.
- Never commit data/, logs/, .env files, credentials, prompts, results, or session histories.
- Planning, reads, startup and archiving must never dispatch work. No silent retry.
- Do not bypass harness approval policies, enable yolo, or expose the loopback server.
- Use literal subprocess argument arrays/stdin, explicit existing project workspaces,
  unknown (not invented) provider limits, and clear terminal failure states.
- Keep changes bounded; document compatibility and only claim checks actually run.
