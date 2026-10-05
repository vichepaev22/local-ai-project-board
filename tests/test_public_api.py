"""Public-server boundary checks; all dispatches are inert local doubles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from runtime_data import initialize_data


class DispatchingNonCodex:
    kind = "hermes"
    online = True

    def __init__(self) -> None:
        self.dispatched: list[list[str]] = []

    def snapshot(self):
        return {"kind": self.kind, "online": True, "message": "test adapter"}

    def available_models(self):
        return []

    def current_budget(self):
        return {"isLive": False, "limitEnforced": False, "dispatchAllowed": True,
                "fiveHour": {"remainingPercent": None}, "weekly": {"remainingPercent": None}}

    def schedule_reconciliation(self, queue):
        return None

    def dispatch_many(self, ids):
        self.dispatched.append(ids)


class PublicAPITests(unittest.TestCase):
    def test_codex_snapshot_declares_mode_even_before_transport_starts(self):
        self.assertEqual(server.CodexBridge().snapshot()['kind'],'codex')
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="public-api-", dir=server.ROOT)
        self.addCleanup(self.temp.cleanup)
        self.old = {key: getattr(server, key) for key in [
            "DATA", "PROJECTS_FILE", "BUDGET_FILE", "QUEUE_FILE", "ACTIVITY_FILE",
            "EVENTS_FILE", "TOMORROW_FILE", "BOARD_FILE", "BRIDGE",
        ]}
        paths = initialize_data(Path(self.temp.name) / "data")
        for key, value in paths.items():
            setattr(server, key, value)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        server.write_json(server.PROJECTS_FILE, [{
            "id": "one", "name": "One", "goal": "Test", "stage": "New", "nextSteps": [],
            "workspace": str(self.workspace.resolve()),
            "route": {"status": "linked", "harness": "codex", "threadId": "thread-one"},
        }])
        server.write_json(server.QUEUE_FILE, [])
        server.write_json(server.ACTIVITY_FILE, [])
        server.write_json(server.TOMORROW_FILE, {"title": "Tomorrow", "tasks": []})
        server.write_json(server.BOARD_FILE, {})
        server.BRIDGE = server.ManualBridge()
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.DashboardHandler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join()
        for key, value in self.old.items():
            setattr(server, key, value)

    def request(self, path, payload=None, *, method=None, headers=None):
        request_headers = dict(headers or {})
        data = None if payload is None else json.dumps(payload).encode()
        if payload is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                return response.status, response.read(), dict(response.headers)
        except HTTPError as error:
            with error:
                return error.code, error.read(), dict(error.headers)

    def json_request(self, *args, **kwargs):
        code, body, _ = self.request(*args, **kwargs)
        return code, json.loads(body) if body else {}

    def test_only_named_root_assets_are_exposed_to_get_and_head(self):
        self.assertEqual(self.request("/board.html")[0], 200)
        for path in ["/data/projects.json", "/server.py", "/%2e%2e/server.py", "/tests/", "/.gitignore"]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
                self.assertEqual(self.request(path, method="HEAD")[0], 404)
        link = server.ROOT / "trusted-test-asset.css"
        server.PUBLIC_ASSETS.add(link.name)
        try:
            try:
                os.symlink(server.ROOT / "server.py", link)
            except OSError as error:
                self.skipTest(f"Symlink creation is unavailable here: {error}")
            self.assertEqual(self.request(f"/{link.name}")[0], 404)
            self.assertEqual(self.request(f"/{link.name}", method="HEAD")[0], 404)
        finally:
            server.PUBLIC_ASSETS.discard(link.name)
            if link.exists() or link.is_symlink():
                link.unlink()

    def test_host_origin_and_json_guards(self):
        payload = {"revision": 0, "op": "settings", "name": "Board", "sprint": "Now", "theme": "warm"}
        self.assertEqual(self.json_request("/api/board", payload, headers={"Host": "example.test:80"})[0], 403)
        self.assertEqual(self.json_request("/api/board", payload, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.json_request("/api/board", payload, headers={"Origin": "http://localhost:9"})[0], 403)
        self.assertEqual(self.json_request("/api/board", payload)[0], 200)  # CLI/no Origin remains supported.

    def test_workspace_is_explicit_and_revision_checked(self):
        add = {"revision": 0, "op": "add-project", "name": "Plan only", "goal": "x", "workspace": ""}
        code, response = self.json_request("/api/board", add)
        self.assertEqual(code, 200)
        project = response["projects"][-1]
        self.assertEqual(project["workspace"], "")
        self.assertEqual(self.json_request("/api/board", {**add, "revision": 1, "name": "Relative", "workspace": "relative"})[0], 400)
        revision = response["board"]["revision"]
        set_workspace = {"revision": revision, "op": "set-workspace", "projectId": project["id"], "workspace": str(self.workspace)}
        self.assertEqual(self.json_request("/api/board", set_workspace)[0], 200)
        self.assertEqual(self.json_request("/api/board", set_workspace)[0], 409)

    def test_manual_never_claims_budget_or_dispatches_and_bridge_health_is_snapshot(self):
        budget = server.BRIDGE.current_budget()
        self.assertFalse(budget["isLive"])
        self.assertFalse(budget["limitEnforced"])
        self.assertFalse(budget["dispatchAllowed"])
        code, health = self.json_request("/api/bridge-health")
        self.assertEqual(code, 200)
        self.assertEqual(health["kind"], "manual")
        _, queued = self.json_request("/api/queue", {"updates": [{"projectId": "one", "kind": "comment", "text": "Plan"}]})
        queue_id = queued["added"][0]["id"]
        self.assertEqual(self.json_request("/api/confirm-dispatch", {"queueIds": [queue_id]})[0], 503)
        self.assertEqual(server.find_queue_item(queue_id)["status"], "queued")

    def test_non_codex_can_dispatch_without_a_fake_codex_quota_but_retry_respects_availability(self):
        bridge = DispatchingNonCodex()
        server.BRIDGE = bridge
        _, queued = self.json_request("/api/queue", {"updates": [{"projectId": "one", "kind": "comment", "text": "Hermes"}]})
        queue_id = queued["added"][0]["id"]
        code, confirmed = self.json_request("/api/confirm-dispatch", {"queueIds": [queue_id]})
        self.assertEqual(code, 202)
        self.assertNotIn("Codex", confirmed['message'])
        self.assertNotIn("Codex", server.find_queue_item(queue_id)['progressStage'])
        self.assertNotIn("Codex", server.read_json(server.ACTIVITY_FILE)[-1]['text'])
        self.assertEqual(server.find_queue_item(queue_id)["status"], "dispatching")
        server.update_queue_item(queue_id, status="failed")
        server.BRIDGE = server.ManualBridge()
        self.assertEqual(self.json_request("/api/retry-dispatch", {"queueId": queue_id})[0], 503)
        self.assertEqual(server.find_queue_item(queue_id)["status"], "failed")

    def test_no_implicit_workspace_and_invalid_workspace_never_resumes(self):
        _, added = self.json_request("/api/board", {"revision": 0, "op": "add-project", "name": "Blank", "goal": "x"})
        blank = added["projects"][-1]
        _, queued = self.json_request("/api/queue", {"updates": [{"projectId": blank["id"], "kind": "comment", "text": "No launch"}]})
        self.assertEqual(self.json_request("/api/confirm-dispatch", {"queueIds": [queued["added"][0]["id"]]})[0], 422)
        projects = server.read_json(server.PROJECTS_FILE)
        projects[0]["workspace"] = "relative"
        server.write_json(server.PROJECTS_FILE, projects)
        server.write_json(server.QUEUE_FILE, [{"id": "bad", "projectId": "one", "status": "dispatching", "route": projects[0]["route"]}])
        bridge = server.CodexBridge()
        with self.assertRaises(server.AppServerError):
            bridge._ensure_route(projects[0])

    def test_workspace_change_rejects_active_work_and_resets_pending_route(self):
        server.write_json(server.QUEUE_FILE, [{"id": "active", "projectId": "one", "status": "running"}])
        payload = {"revision": 0, "op": "set-workspace", "projectId": "one", "workspace": str(self.workspace)}
        self.assertEqual(self.json_request("/api/board", payload)[0], 409)
        server.write_json(server.QUEUE_FILE, [{"id": "queued", "projectId": "one", "status": "queued", "route": {"harness": "codex", "threadId": "thread-one"}}])
        second = Path(self.temp.name) / "workspace-two"
        second.mkdir()
        self.assertEqual(self.json_request("/api/board", {**payload, "workspace": str(second)})[0], 200)
        self.assertIsNone(server.project_by_id("one")["route"]["threadId"])
        self.assertIsNone(server.find_queue_item("queued")["route"]["threadId"])

    def test_fresh_initializer_is_empty_and_does_not_need_a_parent_workspace(self):
        fresh = initialize_data(Path(self.temp.name) / "fresh")
        self.assertEqual(json.loads(fresh["PROJECTS_FILE"].read_text(encoding="utf-8")), [])
        self.assertEqual(json.loads(fresh["QUEUE_FILE"].read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
