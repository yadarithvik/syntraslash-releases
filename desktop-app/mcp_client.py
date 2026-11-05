"""Local MCP stdio transport with explicit server ownership and bounded calls."""
from pathlib import Path
import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

import extensions

_LOCK=threading.RLock()
_CLIENTS={}


def runtime_root():
    if getattr(sys,'frozen',False):return Path(sys.executable).parent
    source=Path(__file__).resolve().parent
    return source if (source/'mcp').is_dir() else source.parent if (source.parent/'mcp').is_dir() else source


def configuration():
    root=runtime_root()
    servers={'rea':{'name':'rea','command':str(root/'mcp/node/node.exe'),'args':[str(root/'mcp/rea/node_modules/rea-agents/scripts/rea.mjs'),'mcp'],'enabled':True,'bundled':True,'package':'rea-agents@6.8.0'}}
    path=extensions.data_root()/'mcp-servers.json'
    if path.exists():servers.update(json.loads(path.read_text(encoding='utf-8')))
    return servers


def save_server(name,command,args,enabled=True):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}',name):raise ValueError('Use a short server name with letters, numbers, hyphens or underscores.')
    if not isinstance(command,str) or not command.strip() or not isinstance(args,list) or len(args)>50 or any(not isinstance(x,str) or len(x)>4000 for x in args):raise ValueError('A command and an array of arguments are required.')
    with _LOCK:
        disconnect(name)
        path=extensions.data_root()/'mcp-servers.json';path.parent.mkdir(parents=True,exist_ok=True)
        data=json.loads(path.read_text()) if path.exists() else {}
        data[name]={'name':name,'command':command,'args':args,'enabled':bool(enabled),'bundled':False}
        temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(data,indent=2));temp.replace(path)
    return data[name]


class StdioClient:
    def __init__(self,spec):
        self.spec=spec;self.seq=0;self.lock=threading.RLock();self.messages=queue.Queue(maxsize=1000);self.tools={}
        command=[spec['command'],*spec['args']]
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,cwd=str(runtime_root()))
        threading.Thread(target=self._read,daemon=True,name='syntra-mcp-stdout').start()
        try:
            initialized=self.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'Syntra Slash','version':'1.3.0'}},timeout=60)
            self.server_info=initialized.get('serverInfo',{})
            self.notify('notifications/initialized',{})
            cursor=None
            for page in range(30):
                result=self.request('tools/list',{'cursor':cursor} if cursor else {},timeout=60)
                for tool in result.get('tools',[]):self.tools[tool['name']]=tool
                cursor=result.get('nextCursor')
                if not cursor:break
            else:raise RuntimeError('MCP tool pagination exceeded 30 pages.')
        except BaseException:self.close();raise

    def _read(self):
        try:
            while True:
                line=self.process.stdout.readline(8*1024*1024+1)
                if not line:break
                if len(line)>8*1024*1024:raise ValueError('MCP response exceeded 8 MB.')
                try:message=json.loads(line)
                except (ValueError,UnicodeError):continue
                self.messages.put(message,timeout=1)
        except Exception as error:
            try:self.messages.put_nowait({'_transport_error':str(error)})
            except queue.Full:pass

    def notify(self,method,params):
        self.process.stdin.write((json.dumps({'jsonrpc':'2.0','method':method,'params':params})+'\n').encode());self.process.stdin.flush()

    def request(self,method,params,timeout=90,cancel_event=None):
        with self.lock:
            self.seq+=1;ident=self.seq
            self.process.stdin.write((json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n').encode());self.process.stdin.flush()
            deadline=time.monotonic()+timeout
            try:
                while time.monotonic()<deadline:
                    if cancel_event and cancel_event.is_set():
                        self.notify('notifications/cancelled',{'requestId':ident,'reason':'User stopped the task.'})
                        raise InterruptedError('MCP request cancelled.')
                    try:message=self.messages.get(timeout=.1)
                    except queue.Empty:
                        if self.process.poll() is not None:raise RuntimeError('MCP server exited.')
                        continue
                    if '_transport_error' in message:raise RuntimeError(message['_transport_error'])
                    if 'method' in message and 'id' in message:
                        # No sampling, elicitation or filesystem-root delegation.
                        self.process.stdin.write((json.dumps({'jsonrpc':'2.0','id':message['id'],'error':{'code':-32601,'message':'Client capability is not supported.'}})+'\n').encode());self.process.stdin.flush();continue
                    if message.get('id')!=ident:continue
                    if message.get('error'):raise RuntimeError(str(message['error'].get('message','MCP error')))
                    return message.get('result',{})
                raise TimeoutError('MCP request timed out. It was not repeated.')
            except (TimeoutError,InterruptedError):
                self.close();raise

    def close(self):
        if self.process.poll() is None:
            try:self.process.stdin.close()
            except OSError:pass
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
                else:self.process.terminate()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        for stream in (self.process.stdin,self.process.stdout):
            if stream:
                try:stream.close()
                except OSError:pass


def connect(name):
    with _LOCK:
        spec=configuration().get(name)
        if not spec or not spec.get('enabled'):raise ValueError('MCP server is disabled or unknown.')
        client=_CLIENTS.get(name)
        if client and client.process.poll() is None:return client
        client=StdioClient(spec);_CLIENTS[name]=client
        return client


def disconnect(name):
    with _LOCK:
        client=_CLIENTS.pop(name,None)
        if client:client.close()


def status():
    with _LOCK:
        items=[]
        for name,spec in configuration().items():
            client=_CLIENTS.get(name)
            installed=Path(spec['command']).is_file() and bool(spec['args']) and Path(spec['args'][0]).is_file() if spec.get('bundled') else True
            items.append({**spec,'installed':installed,'connected':bool(client and client.process.poll() is None),'tool_count':len(client.tools) if client else 0,'server_info':client.server_info if client else None})
        return {'servers':items,'transport':'stdio','notice':'Local MCP processes run with your Windows account. REA native engines are separate prerequisites.'}


def list_tools(name,query='',tool_name=None):
    client=connect(name)
    if tool_name:
        tool_name=canonical_tool_name(name,tool_name)
        tool=client.tools.get(tool_name)
        if not tool:raise ValueError('Tool is not advertised by this server.')
        # REA's output schemas can be much larger than its actual tool inputs.
        # The model needs the complete input contract before making a call.
        contract={key:tool[key] for key in ('name','description','inputSchema') if key in tool}
        return {'success':True,'server':name,'tool_name':tool_name,'output':json.dumps(contract,ensure_ascii=False)}
    tools=[{'name':tool['name'],'description':str(tool.get('description',''))[:400]} for tool in client.tools.values() if query.lower() in (tool['name']+' '+tool.get('description','')).lower()]
    return {'success':True,'total':len(client.tools),'matches':len(tools),'tools':tools[:20],'output':json.dumps(tools[:20],ensure_ascii=False)}


def canonical_tool_name(server,tool_name):
    tool_name=str(tool_name).strip()
    for prefix in (server+'/',server+'.'):
        if tool_name.startswith(prefix):return tool_name[len(prefix):]
    return tool_name


def call_tool(name,tool_name,arguments,cancel_event=None):
    client=connect(name)
    tool_name=canonical_tool_name(name,tool_name)
    if tool_name not in client.tools:raise ValueError('Tool is not advertised by this server. Discover its schema first.')
    if not isinstance(arguments,dict):raise ValueError('MCP arguments must be a JSON object.')
    result=client.request('tools/call',{'name':tool_name,'arguments':arguments},timeout=120,cancel_event=cancel_event)
    raw=json.dumps(result,ensure_ascii=False,indent=2)
    folder=extensions.data_root()/'mcp-evidence';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+'.json');path.write_text(raw,encoding='utf-8')
    text='\n'.join(str(item.get('text','')) for item in result.get('content',[]) if item.get('type')=='text') or raw
    return {'success':not result.get('isError',False),'server':name,'tool':tool_name,'output':text[:2000],'truncated':len(text)>2000,'full_result_path':str(path),'note':'Full response is preserved as readable JSON; use read_file with line ranges for further evidence.'}


def close_all():
    for name in list(_CLIENTS):disconnect(name)


atexit.register(close_all)
