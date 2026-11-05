from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

import extensions
import local_schedule
import mcp_client


FAKE='''import json,sys,time
for line in sys.stdin:
 q=json.loads(line)
 if 'id' not in q:continue
 method=q['method']
 if method=='initialize':result={'protocolVersion':'2025-06-18','serverInfo':{'name':'fixture','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'echo','description':'Fixture echo','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':result={'content':[{'type':'text','text':q['params']['arguments']['value']}]}
 elif method=='slow':time.sleep(5);result={}
 else:
  print(json.dumps({'jsonrpc':'2.0','id':q['id'],'error':{'code':-32601,'message':'Unsupported fixture method'}}),flush=True);continue
 print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':result}),flush=True)
'''


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patch=patch.object(extensions,'data_root',return_value=self.root/'data');self.patch.start()
        self.fake=self.root/'fake.py';self.fake.write_text(FAKE)
    def tearDown(self):mcp_client.close_all();self.patch.stop();self.tmp.cleanup()
    def client(self):return mcp_client.StdioClient({'command':sys.executable,'args':[str(self.fake)]})

    def test_initialize_schema_discovery_and_call(self):
        client=self.client()
        try:
            self.assertIn('echo',client.tools)
            result=client.request('tools/call',{'name':'echo','arguments':{'value':'verified 7169'}})
            self.assertEqual(result['content'][0]['text'],'verified 7169')
        finally:client.close()
        self.assertIsNotNone(client.process.poll())

    def test_json_rpc_errors_are_reported(self):
        client=self.client()
        try:
            with self.assertRaisesRegex(RuntimeError,'Unsupported fixture'):client.request('not-a-method',{})
        finally:client.close()

    def test_input_schema_discovery_omits_large_output_schema(self):
        mcp_client.save_server('fixture',sys.executable,[str(self.fake)])
        client=mcp_client.connect('fixture')
        client.tools['echo']['outputSchema']={'description':'unnecessary-output-schema '*1000}
        result=mcp_client.list_tools('fixture',tool_name='echo')
        contract=json.loads(result['output'])
        self.assertIn('inputSchema',contract);self.assertNotIn('outputSchema',contract)
        self.assertLess(len(result['output']),500)

    def test_timeout_stops_owned_process_without_retry(self):
        client=self.client()
        with self.assertRaises(TimeoutError):client.request('slow',{},timeout=.1)
        self.assertIsNotNone(client.process.poll())

    def test_configuration_and_disabled_connection(self):
        mcp_client.save_server('fixture',sys.executable,[str(self.fake)],False)
        with self.assertRaises(ValueError):mcp_client.connect('fixture')
        with self.assertRaises(ValueError):mcp_client.save_server('../escape','bad',[])

    def test_full_mcp_result_is_retained(self):
        mcp_client.save_server('fixture',sys.executable,[str(self.fake)])
        result=mcp_client.call_tool('fixture','echo',{'value':'x'*18000})
        self.assertTrue(result['truncated'])
        self.assertIn('x'*18000,Path(result['full_result_path']).read_text())
        with self.assertRaises(ValueError):mcp_client.call_tool('fixture','unknown',{})

    def test_qualified_tool_names_are_resolved_only_in_their_server(self):
        mcp_client.save_server('fixture',sys.executable,[str(self.fake)])
        contract=mcp_client.list_tools('fixture',tool_name='fixture/echo')
        self.assertEqual(json.loads(contract['output'])['name'],'echo')
        result=mcp_client.call_tool('fixture','fixture.echo',{'value':'qualified 5381'})
        self.assertTrue(result['success']);self.assertIn('5381',result['output'])
        with self.assertRaises(ValueError):mcp_client.call_tool('fixture','other/echo',{})

    def test_default_skill_adaptations_use_syntra_tools(self):
        items=extensions.list_skills()['skills'];self.assertEqual(len(items),12)
        names={x['name'] for x in items}
        self.assertTrue({'syntra-customizations','automation','generative-ui','migrate-workflows','plugin','run-workflow','reverse-engineer-anything'}<=names)
        for item in items:
            text=Path(item['path']).read_text().lower()
            self.assertNotIn('antigravity',text);self.assertNotIn('gemini',text)

    def test_schedule_timezone_and_idempotent_cancel(self):
        when=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        one=local_schedule.schedule('Test','Read the workspace',when,str(self.root))
        two=local_schedule.schedule('Test','Read the workspace',when,str(self.root))
        self.assertEqual(one['task']['id'],two['task']['id'])
        self.assertEqual(len(local_schedule.list_tasks()),1)
        local_schedule.cancel(one['task']['id']);self.assertEqual(local_schedule.list_tasks()[0]['status'],'cancelled')
        with self.assertRaises(ValueError):local_schedule.schedule('Bad','X','2026-11-08T09:00:00',str(self.root))

    def test_due_schedule_is_claimed_and_dispatched_once(self):
        future=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
        created=local_schedule.schedule('One task','Inspect files',future,str(self.root))
        with local_schedule.LOCK:
            data=local_schedule._load();data[created['task']['id']]['run_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();local_schedule._save(data)
        with patch('session_store.create_session'),patch('session_manager.start_session_task',return_value=(True,'run-fixture')) as run:
            local_schedule.tick();local_schedule.tick();self.assertEqual(run.call_count,1)
        self.assertEqual(local_schedule.list_tasks()[0]['status'],'started')


if __name__=='__main__':unittest.main()
