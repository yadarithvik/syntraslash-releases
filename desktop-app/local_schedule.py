"""Durable one-shot tasks; the Syntra app must be running when they are due."""
from datetime import datetime,timezone
from pathlib import Path
import atexit
import hashlib
import json
import threading
import uuid

import extensions

LOCK=threading.RLock();STOP=threading.Event();THREAD=None


def _load():
    path=extensions.data_root()/'scheduled-tasks.json'
    return json.loads(path.read_text()) if path.exists() else {}


def _save(data):
    path=extensions.data_root()/'scheduled-tasks.json';path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(path)


def schedule(name,prompt,run_at,workspace):
    stamp=datetime.fromisoformat(run_at.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Include a UTC offset in run_at.')
    if stamp<=datetime.now(timezone.utc):raise ValueError('Choose a future time.')
    folder=Path(workspace).resolve(strict=True)
    if not folder.is_dir() or not str(prompt).strip():raise ValueError('A task prompt and existing workspace are required.')
    ident=hashlib.sha256((str(folder)+prompt+stamp.isoformat()).encode()).hexdigest()[:20]
    with LOCK:
        data=_load()
        if ident not in data:
            data[ident]={'id':ident,'name':str(name)[:100],'prompt':prompt[:10000],'run_at':stamp.isoformat(),'workspace':str(folder),'status':'pending'}
            _save(data)
        return {'success':True,'task':data[ident],'output':json.dumps(data[ident]),'notice':'Syntra must be open. A missed pending task runs next time Syntra opens; interrupted claims are not silently repeated.'}


def list_tasks():
    with LOCK:return list(_load().values())


def cancel(ident):
    with LOCK:
        data=_load()
        if ident not in data or data[ident]['status']!='pending':raise ValueError('Only a pending scheduled task can be cancelled here.')
        data[ident]['status']='cancelled';_save(data)
        return {'success':True,'output':'Cancelled '+ident}


def tick():
    import session_store
    import session_manager
    with LOCK:
        data=_load();now=datetime.now(timezone.utc)
        for ident,task in data.items():
            if task['status']!='pending' or datetime.fromisoformat(task['run_at'])>now:continue
            task['status']='claimed';task['session_id']='scheduled-'+ident;_save(data)
            try:
                session_store.create_session({'id':task['session_id'],'title':task['name'],'workspace':task['workspace'],'mode':'background'})
                ok,run_id=session_manager.start_session_task(task['session_id'],task['prompt'])
                task.update(status='started' if ok else 'failed',run_id=run_id)
            except Exception as error:task.update(status='failed',error=str(error))
            _save(data)


def start():
    global THREAD
    with LOCK:
        if THREAD and THREAD.is_alive():return
        STOP.clear()
        def loop():
            while not STOP.wait(5):
                try:tick()
                except Exception:pass
        THREAD=threading.Thread(target=loop,daemon=True,name='syntra-schedule');THREAD.start()


atexit.register(STOP.set)
