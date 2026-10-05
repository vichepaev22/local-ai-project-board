"""Disposable browser fixture. Never connects to Codex or changes portfolio data."""
import tempfile
import sys
from datetime import datetime, timedelta, timezone
from test_board import install_fixture, server

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="portfolio-preview-") as directory:
        install_fixture(directory)
        projects=server.read_json(server.PROJECTS_FILE)
        if '--journal' in sys.argv:
            stamp=datetime.now(timezone.utc).isoformat()
            queue=[]
            for index,status in enumerate(['completed','failed','running','queued','failed']):
                project=server.read_json(server.PROJECTS_FILE)[index%2]
                queue.append({'id':f'journal-{index}','projectId':project['id'],'projectName':project['name'],
                    'status':status,'kind':'next-step','scope':'small','text':f'Тестовое поручение {index+1}. Настоящий Codex отключён.',
                    'route':project['route'],'createdAt':f'2026-09-0{index+1}T10:00:00+05:00','lastEventAt':stamp if status=='running' else f'2026-09-0{index+1}T12:00:00+05:00',
                    'result':'Сохранённый тестовый результат' if status=='completed' else None,
                    **({'archivedAt':stamp} if index==4 else {})})
            server.write_json(server.QUEUE_FILE,queue)
        if '--execution' in sys.argv:
            states=['running','dispatching','waiting-user','waiting-busy','failed','completed','queued','running']
            queue=[]
            for index, status in enumerate(states):
                p=projects[index%len(projects)]
                at=datetime.now(timezone.utc)-timedelta(seconds=180 if index==7 else 0)
                queue.append({'id':f'fixture-{index}','projectId':p['id'],'projectName':p['name'],'status':status,'kind':'next-step','scope':'small','text':'Только тестовая среда: проверить индикацию','lastEventAt':at.isoformat(),'createdAt':at.isoformat(),'progress':55 if status=='running' else 0,'progressStage':'Тестовый исполнитель: проверяет интерфейс','error':'The model requires a newer version of Codex' if status=='failed' else None})
            server.write_json(server.QUEUE_FILE,queue)
        with server.ThreadingHTTPServer(("127.0.0.1",5138),server.DashboardHandler) as http:
            print("Isolated UI preview http://127.0.0.1:5138",flush=True)
            http.serve_forever()
