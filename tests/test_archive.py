"""Real archive HTTP operations with a disposable queue; no Codex connection."""
import copy
import unittest
import test_board

server = test_board.server


class ArchiveTests(unittest.TestCase):
    setUp = test_board.HTTPTests.setUp
    tearDown = test_board.HTTPTests.tearDown
    request = test_board.HTTPTests.request

    def seed(self, status='completed', **extra):
        item = {'id':'done','projectId':'one','projectName':'Тест','status':status,'scope':'small',
                'createdAt':'2026-09-01T10:00:00+05:00','lastEventAt':'2026-09-02T10:00:00+05:00',
                'result':'Полный результат','history':[{'status':'completed','text':'Готово'}],**extra}
        server.write_json(server.QUEUE_FILE,[item])
        return copy.deepcopy(item)

    def test_archive_and_restore_preserve_result_dates_and_history_without_dispatch(self):
        original=self.seed()
        code,data=self.request('/api/queue/archive',{'queueIds':['done'],'archived':True})
        self.assertEqual(code,200)
        saved=server.find_queue_item('done')
        self.assertTrue(saved.pop('archivedAt'))
        self.assertEqual(saved,original)
        self.assertTrue(self.request('/api/state')[1]['queue'][0]['archivedAt'])
        code,_=self.request('/api/queue/archive',{'queueIds':['done'],'archived':False})
        self.assertEqual(code,200)
        self.assertEqual(server.find_queue_item('done'),original)

    def test_batch_is_atomic_if_any_task_is_not_finished(self):
        original=self.seed()
        for status in ['queued','dispatching','running','waiting-user','waiting-busy','blocked-external-access']:
            with self.subTest(status=status):
                items=[original,{'id':'active','status':status}]
                server.write_json(server.QUEUE_FILE,items)
                code,_=self.request('/api/queue/archive',{'queueIds':['done','active'],'archived':True})
                self.assertEqual(code,409)
                self.assertEqual(server.read_json(server.QUEUE_FILE),items)

    def test_unknown_ids_and_invalid_requests_never_partially_archive(self):
        original=self.seed()
        for payload,expected in [({'queueIds':['done','missing'],'archived':True},409),
                                 ({'queueIds':[],'archived':True},400),
                                 ({'queueIds':['done'],'archived':'false'},400),
                                 ({'queueIds':[{}],'archived':True},400)]:
            with self.subTest(payload=payload):
                self.assertEqual(self.request('/api/queue/archive',payload)[0],expected)
                self.assertEqual(server.find_queue_item('done'),original)

    def test_repeated_archive_is_idempotent_and_failed_items_are_supported(self):
        self.seed('failed')
        payload={'queueIds':['done','done'],'archived':True}
        self.assertEqual(self.request('/api/queue/archive',payload)[0],200)
        before=server.find_queue_item('done')
        activity=server.read_json(server.ACTIVITY_FILE)
        self.assertEqual(self.request('/api/queue/archive',payload)[0],200)
        self.assertEqual(server.find_queue_item('done'),before)
        self.assertEqual(server.read_json(server.ACTIVITY_FILE),activity)

    def test_archived_failure_cannot_be_retried(self):
        original=self.seed('failed',archivedAt='2026-09-03T10:00:00+05:00')
        self.assertEqual(self.request('/api/retry-dispatch',{'queueId':'done'})[0],409)
        self.assertEqual(server.find_queue_item('done'),original)

    def test_retry_does_not_resend_archived_sibling_from_same_turn(self):
        original=self.seed('failed',turnId='old-turn',archivedAt='2026-09-03T10:00:00+05:00')
        sibling={**original,'id':'retry'};sibling.pop('archivedAt')
        server.write_json(server.QUEUE_FILE,[original,sibling])
        code,data=self.request('/api/retry-dispatch',{'queueId':'retry'})
        self.assertEqual(code,202)
        self.assertEqual(data['started'],['retry'])
        self.assertEqual(server.find_queue_item('done'),original)

    def test_confirm_preserves_archive_written_while_budget_is_being_checked(self):
        original=self.seed()
        self.request('/api/queue',{'updates':[{'projectId':'one','kind':'next-step','scope':'small','text':'Тестовая задача'}]})
        queued=next(q for q in server.read_json(server.QUEUE_FILE) if q['status']=='queued')
        budget=server.BRIDGE.current_budget()
        def budget_during_archive():
            items=server.read_json(server.QUEUE_FILE)
            items[0]['archivedAt']='2026-09-03T10:00:00+05:00'
            server.write_json(server.QUEUE_FILE,items)
            return budget
        server.BRIDGE.current_budget=budget_during_archive
        self.assertEqual(self.request('/api/confirm-dispatch',{'queueIds':[queued['id']]})[0],202)
        self.assertEqual(server.find_queue_item('done'),{**original,'archivedAt':'2026-09-03T10:00:00+05:00'})


if __name__=='__main__':unittest.main()
