"""Exercise real dispatch/grouping logic with only the RPC transport replaced."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_board import install_fixture, server


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='portfolio-dispatch-test-')
        self.addCleanup(self.temp.cleanup)
        original = {key: getattr(server, key) for key in ['PROJECTS_FILE','QUEUE_FILE','ACTIVITY_FILE','BOARD_FILE','TOMORROW_FILE','BUDGET_FILE','EVENTS_FILE','BRIDGE']}
        self.addCleanup(lambda: [setattr(server, key, value) for key, value in original.items()])
        install_fixture(self.temp.name)
        project=server.project_by_id('one')
        self.items=[{'id':f'q{i}','projectId':'one','text':f'Запрос {i}','kind':'next-step',
                     'status':'dispatching','route':project['route']} for i in [1,2]]
        server.write_json(server.QUEUE_FILE,self.items)

    def test_related_requests_resume_existing_thread_and_start_exactly_one_turn(self):
        calls=[]
        def rpc(method, params, **kwargs):
            calls.append((method,params))
            if method=='thread/resume':
                self.assertEqual(params['threadId'],'test-one')
                return {'thread':{'id':'test-one'}}
            if method=='turn/start':
                self.assertEqual(params['threadId'],'test-one')
                self.assertNotIn('model',params)
                self.assertIn('Запрос 1',params['input'][0]['text'])
                self.assertIn('Запрос 2',params['input'][0]['text'])
                return {'turn':{'id':'new-turn','status':'inProgress'}}
            self.fail(f'Unexpected RPC: {method}')
        bridge=server.CodexBridge()
        with patch.object(bridge,'request',side_effect=rpc):
            bridge.dispatch_many(['q1','q2'])
        self.assertEqual([c[0] for c in calls],['thread/resume','turn/start'])
        for item in server.read_json(server.QUEUE_FILE):
            self.assertEqual(item['status'],'running')
            self.assertEqual(item['turnId'],'new-turn')
            self.assertEqual(item['route']['threadId'],'test-one')

    def test_resume_failure_never_claims_that_work_started(self):
        bridge=server.CodexBridge()
        def rpc(method, params, **kwargs):
            self.assertEqual(method,'thread/resume')
            raise server.AppServerError('unknown variant functionCallOutput')
        with patch.object(bridge,'request',side_effect=rpc):
            bridge.dispatch_many(['q1','q2'])
        for item in server.read_json(server.QUEUE_FILE):
            self.assertEqual(item['status'],'failed')
            self.assertNotIn('turnId',item)
            self.assertIn('functionCallOutput',item['error'])

    def test_new_route_preserves_terminal_and_archived_result_provenance(self):
        projects = server.read_json(server.PROJECTS_FILE)
        projects[0]['route'] = {'status': 'auto-create', 'threadId': None}
        server.write_json(server.PROJECTS_FILE, projects)
        historical = [
            {'id': status, 'projectId': 'one', 'status': status,
             'route': {'harness': 'codex', 'threadId': 'historical-thread'},
             'result': 'Historical result'}
            for status in ['completed', 'failed', 'interrupted']
        ]
        historical.append({**historical[0], 'id': 'archived', 'archivedAt': server.now()})
        server.write_json(server.QUEUE_FILE, [*self.items, *historical])
        bridge = server.CodexBridge()
        with patch.object(bridge, 'request', return_value={'thread': {'id': 'new-thread'}}):
            bridge._ensure_route(projects[0])
        self.assertEqual(server.project_by_id('one')['route']['threadId'], 'new-thread')
        self.assertEqual(server.find_queue_item('q1')['route']['threadId'], 'new-thread')
        for item in historical:
            self.assertEqual(server.find_queue_item(item['id']), item)


if __name__=='__main__':
    unittest.main()
