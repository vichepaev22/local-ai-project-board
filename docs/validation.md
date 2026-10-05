# Validation record — 2026-10-05

Confirmed locally on Windows, Python 3.14, Node 24.11.1:
- Initial local Python suite: 64 tests, OK, 1 skipped (Windows symlink privilege unavailable).
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

Publication verified: the public GitHub repository and downloaded clone shared the
same commit. The clean clone had no runtime directories before launch; manual startup
returned empty projects/queue, and graceful stop succeeded. Clone suites: 64 Python
tests (1 skipped), 50 JavaScript tests.

The first GitHub CI run passed on Ubuntu but exposed a Windows ANSI-stdin synthetic
child failure and a macOS foreground-start timeout. Child Python streams are now
explicit UTF-8; service binding avoids reverse DNS. A regression test ensures local
binding never calls getfqdn; startup-failure diagnostics and child cleanup were improved.
Final code commit `8688125`: all six GitHub matrix jobs passed (Windows/Linux/macOS,
Python 3.11 and 3.14, Node 22). Each runs Python and frontend tests.
Evidence: [successful CI run](https://github.com/vichepaev22/local-ai-project-board/actions/runs/37310047835).
The updated downloaded clone passed 65 Python tests (1 local symlink privilege skip);
the frontend remained 50 passing tests. Original private board health was rechecked.

Not claimed: real paid-provider execution, every Hermes/Codex version, universal
automatic harness support, OS isolation, or correctness of model-generated work.
Forced server termination or deliberately detached tools can leave external activity;
check it before retry. CI proves the tested OS/Python matrix, not live provider or
every harness version compatibility.
