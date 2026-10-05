"""Isolated regression checks: no real Codex processes or user data writes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from board import BoardConflict, apply_operation, chat_url, normalize_board


class FakeBridge:
    kind = "codex"
    def available_models(self):
        return [{'id':'test-fast', 'label':'Test Fast', 'isDefault':True, 'supportedReasoningEfforts':['low','medium'], 'defaultReasoningEffort':'medium'}, {'id':'test-deep', 'label':'Test Deep', 'isDefault':False, 'supportedReasoningEfforts':['low','medium','high'], 'defaultReasoningEffort':'high'}]

    def current_budget(self):
        return {"isLive": True, "capturedAt": server.now(), "note": "Тестовая среда: отправка в настоящий Codex отключена.", "fiveHour": {"remainingPercent": 50, "resetsAt": 1800000000}, "weekly": {"remainingPercent": 70, "resetsAt": 1800500000}}

    def snapshot(self):
        return {"kind":"codex", "online": True, "message": "Изолированная проверка интерфейса"}

    def schedule_reconciliation(self, queue):
        pass

    def dispatch_many(self, ids):
        for queue_id in ids:
            server.update_queue_item(queue_id, status="running", progress=55, lastEventAt=server.now(), progressStage="Тестовый исполнитель работает")


def install_fixture(directory, projects=None):
    for key, name in {"PROJECTS_FILE":"projects.json", "QUEUE_FILE":"queue.json", "ACTIVITY_FILE":"activity.json", "BOARD_FILE":"board.json", "TOMORROW_FILE":"tomorrow-plan.json", "BUDGET_FILE":"budget.json", "EVENTS_FILE":"events.jsonl"}.items():
        setattr(server, key, Path(directory) / name)
    projects = projects or [{"id": "one", "name": "Проверка один", "stage": "Тест", "goal": "Проверить интерфейс", "nextSteps": ["Первый шаг"], "workspace": directory, "route": {"status": "linked", "label": "Тестовая задача", "threadId": "test-one"}}, {"id": "two", "name": "Проверка два", "stage": "Тест", "goal": "Второй проект", "nextSteps": [], "workspace": directory, "route": {"status": "linked", "label": "Тестовая задача", "threadId": "test-two"}}]
    server.write_json(server.PROJECTS_FILE, projects)
    server.write_json(server.QUEUE_FILE, [])
    server.write_json(server.ACTIVITY_FILE, [])
    server.write_json(server.TOMORROW_FILE, {"title":"Тестовый фокус", "tasks":[]})
    server.BRIDGE = FakeBridge()


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.board = normalize_board({}, [{"id":"one"},{"id":"two"},{"id":"three"}])

    def test_move_and_reorder_keeps_every_card_once(self):
        first = apply_operation(self.board,{"revision":0,"op":"move","projectId":"two","columnId":"sprint"})
        second = apply_operation(first,{"revision":1,"op":"move","projectId":"three","columnId":"sprint","beforeId":"two"})
        self.assertEqual(next(c for c in second["columns"] if c["id"]=="sprint")["cards"],["three","two"])
        self.assertEqual(sorted(i for c in second["columns"] for i in c["cards"]),["one","three","two"])
        self.assertEqual(self.board["revision"],0)

    def test_conflict_preserves_other_window(self):
        changed=apply_operation(self.board,{"revision":0,"op":"card","projectId":"one","changes":{"urgent":True}})
        with self.assertRaises(BoardConflict):
            apply_operation(changed,{"revision":0,"op":"card","projectId":"one","changes":{"urgent":False}})
        self.assertTrue(changed["cards"]["one"]["urgent"])

    def test_new_projects_preserve_positions(self):
        changed=apply_operation(self.board,{"revision":0,"op":"move","projectId":"one","columnId":"review"})
        normalized=normalize_board(changed,[{"id":"one"},{"id":"two"},{"id":"three"},{"id":"four"}])
        self.assertIn("one",next(c for c in normalized["columns"] if c["id"]=="review")["cards"])
        self.assertIn("four",normalized["columns"][0]["cards"])

    def test_untrusted_links_are_rejected(self):
        for url in ["javascript:alert(1)","https://chatgpt.com.evil.test/", "http://chatgpt.com/", "https://user:password@chatgpt.com/"]:
            with self.assertRaises(ValueError): chat_url(url)
        self.assertEqual(chat_url("https://chatgpt.com/g/example/project"),"https://chatgpt.com/g/example/project")

    def test_invalid_card_edit_is_atomic(self):
        old=copy.deepcopy(self.board)
        with self.assertRaises(ValueError):
            apply_operation(self.board,{"revision":0,"op":"card","projectId":"one","changes":{"title":"new","color":"invalid"}})
        self.assertEqual(self.board,old)

    def test_history_records_real_diffs_and_not_noops(self):
        moved=apply_operation(self.board,{"revision":0,"op":"move","projectId":"one","columnId":"review"})
        self.assertEqual(moved["history"][0]["changes"][0],{"field":"Колонка","before":"Идеи","after":"Проверка"})
        edited=apply_operation(moved,{"revision":1,"op":"card","projectId":"one","changes":{"notes":"Проверить пилот","urgent":True}})
        self.assertEqual(len(edited["history"]),2)
        self.assertEqual(edited["history"][1]["projectId"],"one")
        noop=apply_operation(edited,{"revision":2,"op":"card","projectId":"one","changes":{"urgent":True}})
        self.assertEqual(noop["history"],edited["history"])
        self.assertEqual(normalize_board(noop,[{"id":"one"},{"id":"two"}])["history"],noop["history"])

    def test_rename_column_logs_only_projects_in_that_column(self):
        moved=apply_operation(self.board,{"revision":0,"op":"move","projectId":"one","columnId":"review"})
        renamed=apply_operation(moved,{"revision":1,"op":"rename-column","columnId":"review","name":"Приёмка"})
        self.assertEqual(renamed["history"][-1]["projectId"],"one")
        self.assertEqual(renamed["history"][-1]["changes"][0]["after"],"Приёмка")


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="portfolio-board-test-")
        self.old={key:getattr(server,key) for key in ["PROJECTS_FILE","QUEUE_FILE","ACTIVITY_FILE","BOARD_FILE","TOMORROW_FILE","BUDGET_FILE","EVENTS_FILE","BRIDGE"]}
        install_fixture(self.temp.name)
        self.http=server.ThreadingHTTPServer(("127.0.0.1",0),server.DashboardHandler)
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start()
        self.base=f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.worker.join()
        for key,value in self.old.items():setattr(server,key,value)
        self.temp.cleanup()

    def request(self,path,data=None):
        req=Request(self.base+path, data=json.dumps(data).encode() if data is not None else None, headers={"Content-Type":"application/json"})
        try:
            with build_opener(ProxyHandler({})).open(req,timeout=4) as response:return response.status,json.load(response)
        except HTTPError as error:
            with error:return error.code,json.load(error)

    def test_saved_board_reload_and_conflict(self):
        code,data=self.request("/api/board",{"revision":0,"op":"move","projectId":"one","columnId":"done"})
        self.assertEqual(code,200)
        self.assertEqual(self.request("/api/board")[1]["board"],data["board"])
        self.assertEqual(self.request("/api/board",{"revision":0,"op":"move","projectId":"two","columnId":"done"})[0],409)
        self.assertEqual(server.read_json(server.QUEUE_FILE),[])

    def test_charge_does_not_dispatch_and_confirm_checks_budget(self):
        code,data=self.request("/api/queue",{"updates":[{"projectId":"one","kind":"goal","scope":"normal","text":"Проверить цель"}]})
        self.assertEqual(code,201);qid=data["added"][0]["id"]
        self.assertEqual(server.find_queue_item(qid)["status"],"queued")
        server.BRIDGE.current_budget=lambda:{"isLive":False}
        self.assertEqual(self.request("/api/confirm-dispatch",{"queueIds":[qid]})[0],503)
        self.assertEqual(server.find_queue_item(qid)["status"],"queued")

    def test_add_card_preserves_existing_projects(self):
        code,data=self.request("/api/board",{"revision":0,"op":"add-project","name":"Новый проект","goal":"Пилот","columnId":"sprint"})
        self.assertEqual(code,200);self.assertEqual(len(data["projects"]),3)
        self.assertEqual(data["projects"][-1]["name"],"Новый проект")
        self.assertEqual(server.read_json(server.QUEUE_FILE),[])

    def test_history_persists_without_dispatch_or_fake_prior_events(self):
        _,data=self.request("/api/queue",{"updates":[{"projectId":"one","kind":"next-step","text":"Проверить форму"}]})
        qid=data["added"][0]["id"]
        server.update_queue_item(qid,status="running",progressStage="Работа началась")
        server.update_queue_item(qid,progress=60)
        server.update_queue_item(qid,status="completed",completedAt=server.now(),result="Проверено")
        item=server.find_queue_item(qid)
        self.assertEqual([e["status"] for e in item["history"]],["running","completed"])
        _,data=self.request("/api/board",{"revision":0,"op":"card","projectId":"one","changes":{"notes":"Новая заметка"}})
        saved=self.request("/api/board")[1]["board"]
        self.assertEqual(saved["history"],data["board"]["history"])
        self.assertEqual(len(saved["history"]),1)


if __name__=="__main__":unittest.main()
