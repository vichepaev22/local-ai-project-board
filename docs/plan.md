# Delivery plan and file ownership

1. CONTEXT/SPEC/MEMORY/CONTRACT: inspect original, confirm Hermes requirement,
   define interfaces and acceptance in spec.md/decisions.md (lead).
2. RED: run inherited tests; add fresh-start, privacy, workspace, manual, and
   Hermes lifecycle tests before changes. Preserve valid inherited assertions.
3. Small independent slices:
   - Backend worker owns server.py + tests/test_public_api.py; bridge selection,
     manual adapter, private static protection, workspace validation, legacy
     model/effort defect. No UI or other workers' files.
   - Hermes worker owns hermes_bridge.py + tests/test_hermes.py; CLI adapter,
     event parsing, bounded process execution, same-project locking, recovery.
   - Launcher worker owns runtime_data.py, run.py, dashboard_service.py,
     Start-Dashboard.cmd/ps1, start.sh, tests/test_portability.py.
   - Lead owns board.py, UI assets, README/docs/license/ignore/CI and integration.
4. GREEN: full deterministic suites, fresh-data HTTP scenario for each supported
   mode using fake harnesses, literal prompt/injection/timeout/error cases.
5. Independent reviewer: privacy/security and acceptance; repair findings and rerun.
6. Publish a new public GitHub repo, verify remote identity/content and fresh clone.
   Record actual test/CI/provider outcomes and limits, never assume results.

Author and reviewer are distinct. Workers preserve others' changes. The lead owns
integration, acceptance, final Git commit/push and the private-data publication gate.
