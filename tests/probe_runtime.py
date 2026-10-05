"""Read-only compatibility probe: no turn/start, resume, messages or queue writes."""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_runtime import resolve_runtime


def probe(executable, thread_ids):
    process = subprocess.Popen([executable, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    responses = queue.Queue()
    def reader():
        for line in process.stdout:
            try: responses.put(json.loads(line))
            except json.JSONDecodeError: pass
    threading.Thread(target=reader, daemon=True).start()
    seq = 0
    def rpc(method, params):
        nonlocal seq
        seq += 1
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params})+'\n')
        process.stdin.flush()
        while True:
            response = responses.get(timeout=30)
            if response.get('id') == seq:
                if 'error' in response: raise RuntimeError(str(response['error'])[:800])
                return response.get('result', {})
    try:
        rpc('initialize', {'clientInfo':{'name':'portfolio-readonly-check','version':'1.0'},'capabilities':{'experimentalApi':True}})
        process.stdin.write('{"jsonrpc":"2.0","method":"initialized","params":{}}\n')
        process.stdin.flush()
        models=rpc('model/list', {'limit':100})
        print(json.dumps({'models':[m.get('id') for m in models.get('data', [])]},ensure_ascii=False),flush=True)
        for tid in thread_ids:
            try:
                result=rpc('thread/read', {'threadId':tid,'includeTurns':True})
                thread=result.get('thread',{})
                print(json.dumps({'threadId':tid,'readable':True,'turns':len(thread.get('turns',[]))}),flush=True)
            except (RuntimeError,queue.Empty) as error:
                print(json.dumps({'threadId':tid,'readable':False,'error':str(error)},ensure_ascii=False),flush=True)
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--executable')
    parser.add_argument('--thread',action='append',default=[])
    args=parser.parse_args()
    executable=args.executable or resolve_runtime()['executable']
    print(json.dumps({'executable':executable}),flush=True)
    probe(executable,args.thread)
