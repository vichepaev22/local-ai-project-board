# Validation record — 2026-10-05

Confirmed locally on Windows, Python 3.14, Node 24.11.1:
- Python suite: 64 tests, OK, 1 skipped (Windows symlink privilege unavailable).
- JavaScript suite: 50 tests passed.
- Fresh-data foreground/background HTTP startup, occupied-port identity rejection,
  custom data directory, graceful stop, revision conflicts, static/privacy boundary,
  manual dispatch/retry denial, Codex routing/model effort, Hermes lifecycle/error tests.
- A real **synthetic Python child process**, not Hermes/provider inference, exercises
  literal stdin and output-size limits. Other transports are mocked.
- Browser: empty board, card creation, saving a request, manual auto-run disabled,
  copy control present; no console errors observed. Screenshot uses fictional data.
- No original board files/data were exported or changed. Runtime directories ignored.

Independent review identified a Hermes child-process shutdown risk. Ownership registry,
graceful cleanup, late-result guards, bounded output, and regression tests were added.
Re-review confirmed the lifecycle repair by inspection. Independent checks do not
certify all providers. Reported Hermes version/help and actual installed stream module
are checked separately; a historical reported commit is not proof of source identity.
Independent source review confirmed the installed Hermes single-query JSONL contract.
Route-history preservation and neutral executor labels passed regression checks.

Not claimed: real paid-provider execution, every Hermes/Codex version, universal
automatic harness support, OS isolation, or correctness of model-generated work.
Forced server termination or deliberately detached tools can leave external activity;
check it before retry. Linux/macOS runtime compatibility is subject to CI results.
