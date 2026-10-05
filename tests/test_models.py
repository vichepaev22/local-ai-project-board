"""Model choices must survive queueing and reach RPC, without real Codex work."""
import unittest
from unittest.mock import patch
import test_board
import test_dispatch
server = test_board.server


class ModelAPITests(unittest.TestCase):
    setUp = test_board.HTTPTests.setUp
    tearDown = test_board.HTTPTests.tearDown
    request = test_board.HTTPTests.request

    def test_catalog_is_read_only(self):
        code, data = self.request('/api/models')
        self.assertEqual(code, 200)
        self.assertEqual(data['models'][0]['id'], 'test-fast')
        self.assertEqual(server.read_json(server.QUEUE_FILE), [])

    def test_choice_is_saved_and_unknown_models_reject_entire_batch(self):
        update = {'projectId':'one', 'kind':'next-step', 'text':'Проверить модель', 'model':'test-fast'}
        code, data = self.request('/api/queue', {'updates':[update]})
        self.assertEqual(code, 201)
        self.assertEqual(data['added'][0]['model'], 'test-fast')
        self.assertEqual(data['added'][0]['modelLabel'], 'Test Fast')
        before = server.read_json(server.QUEUE_FILE)
        self.assertEqual(self.request('/api/queue', {'updates':[update, {**update, 'model':'unknown'}]})[0], 400)
        self.assertEqual(server.read_json(server.QUEUE_FILE), before)
        self.assertEqual(self.request('/api/queue', {'updates':[{**update, 'model':['test-fast']} ]})[0], 400)

    def test_default_does_not_depend_on_catalog(self):
        with patch.object(server.BRIDGE, 'available_models', side_effect=server.AppServerError('offline')):
            code, data = self.request('/api/queue', {'updates':[{'projectId':'one', 'kind':'comment', 'text':'Как раньше'}]})
            self.assertEqual(code, 201)
            self.assertIsNone(data['added'][0]['model'])
            self.assertEqual(self.request('/api/models')[0], 503)

    def test_mixed_models_cannot_be_silently_merged(self):
        updates = [{'projectId':'one', 'kind':'comment', 'text':'Запрос', 'model':model} for model in ['test-fast', None]]
        _, data = self.request('/api/queue', {'updates':updates})
        ids = [q['id'] for q in data['added']]
        with patch.object(server.BRIDGE, 'dispatch_many') as dispatch:
            self.assertEqual(self.request('/api/confirm-dispatch', {'queueIds':ids})[0], 409)
            dispatch.assert_not_called()
        self.assertTrue(all(q['status']=='queued' for q in server.read_json(server.QUEUE_FILE)))


class ModelDispatchTests(unittest.TestCase):
    setUp = test_dispatch.DispatchTests.setUp

    def test_explicit_model_reaches_turn_start_and_retry(self):
        for item in self.items:
            item['model'] = 'test-fast'
        server.write_json(server.QUEUE_FILE, self.items)
        bridge = server.CodexBridge()
        calls = []
        def rpc(method, params, **kwargs):
            calls.append((method, params))
            if method == 'turn/start':
                self.assertEqual(params['model'], 'test-fast')
                self.assertEqual(params['effort'], 'medium')
                return {'turn':{'id':'model-turn'}}
            return {'thread':{'id':'test-one'}, 'reasoningEffort':'ultra'}
        with patch.object(bridge, 'request', side_effect=rpc), patch.object(bridge, 'available_models', return_value=server.BRIDGE.available_models()):
            bridge.dispatch_many(['q1', 'q2'])
            for q in server.read_json(server.QUEUE_FILE):
                self.assertEqual(q['model'], 'test-fast')
                server.update_queue_item(q['id'], status='dispatching')
            bridge.dispatch_many(['q1', 'q2'])
        self.assertEqual(sum(method=='turn/start' for method, _ in calls), 2)

    def test_new_thread_uses_selected_model_and_preserves_supported_effort(self):
        projects = server.read_json(server.PROJECTS_FILE)
        projects[0]['route'] = {'status':'auto-create', 'threadId':None}
        server.write_json(server.PROJECTS_FILE, projects)
        for item in self.items:
            item['model'] = 'test-fast'
        server.write_json(server.QUEUE_FILE, self.items)
        bridge = server.CodexBridge()
        calls = []
        def rpc(method, params, **kwargs):
            calls.append(method)
            if method == 'turn/start':
                self.assertEqual(params['threadId'], 'created-thread')
                self.assertEqual(params['model'], 'test-fast')
                self.assertEqual(params['effort'], 'low')
                return {'turn':{'id':'created-turn'}}
            return {'thread':{'id':'created-thread'}, 'reasoningEffort':'low'}
        with patch.object(bridge, 'request', side_effect=rpc), patch.object(bridge, 'available_models', return_value=server.BRIDGE.available_models()):
            bridge.dispatch_many(['q1','q2'])
        self.assertEqual(calls, ['thread/start','thread/setName','turn/start'])
        self.assertEqual(server.project_by_id('one')['route']['threadId'], 'created-thread')

    def test_unavailable_and_mixed_models_do_not_start_or_resume(self):
        for models in [('removed', 'removed'), ('test-fast', None)]:
            with self.subTest(models=models):
                for item, model in zip(self.items, models):
                    item['model'] = model
                server.write_json(server.QUEUE_FILE, self.items)
                bridge = server.CodexBridge()
                with patch.object(bridge, 'request') as rpc, patch.object(bridge, 'available_models', return_value=server.BRIDGE.available_models()):
                    bridge.dispatch_many(['q1', 'q2'])
                    rpc.assert_not_called()
                self.assertTrue(all(q['status']=='failed' for q in server.read_json(server.QUEUE_FILE)))


class CatalogTests(unittest.TestCase):
    def test_malformed_catalog_is_a_displayable_error(self):
        for data in [None, {}, [None]]:
            bridge=server.CodexBridge()
            with patch.object(bridge, 'request', return_value={'data':data}):
                with self.assertRaises(server.AppServerError):bridge.available_models()

    def test_catalog_uses_model_slug_filters_hidden_and_reads_all_pages(self):
        bridge = server.CodexBridge()
        pages = [{'data':[{'id':'row-id','model':'real-model','displayName':'Real Model'}, {'id':'hidden','model':'secret','hidden':True}], 'nextCursor':'page2'}, {'data':[{'id':'row2','model':'second','displayName':'Second'}]}]
        with patch.object(bridge, 'request', side_effect=pages) as rpc:
            result = bridge.available_models()
            self.assertEqual([m['id'] for m in result], ['real-model', 'second'])
            self.assertEqual(rpc.call_args_list[1].args[1]['cursor'], 'page2')
            self.assertEqual(bridge.available_models(), result)
            self.assertEqual(rpc.call_count, 2)


if __name__ == '__main__':
    unittest.main()
