from unittest.mock import patch
import json
import unittest

import session_manager


class Memory:
    last_stats={}
    def __init__(self,*args,**kwargs):pass
    def bootstrap(self,*args):pass
    def prepare(self,messages,*args):return messages
    def remember_messages(self,*args):pass
    def record(self,*args):pass
    def compact(self,*args):return {'path':'fixture.md'}


class CompletionObservationTests(unittest.TestCase):
    def test_completion_waits_for_observed_results_in_either_batch_order(self):
        for complete_first in (False,True):
            with self.subTest(complete_first=complete_first):
                saved=[];calls=[]
                def tc(name,args):return {'id':name,'function':{'name':name,'arguments':json.dumps(args)}}
                read=tc('read_file',{'path':'evidence.txt'});wrong=tc('complete_task',{'summary':'guessed 1111'})
                def model(messages,**kwargs):
                    calls.append(messages[:])
                    if len(calls)==1:return {'content':'','tool_calls':[wrong,read] if complete_first else [read,wrong]}
                    results=[m['content'] for m in messages if m['role']=='tool']
                    self.assertTrue(any('7415' in r for r in results))
                    self.assertTrue(any('Completion deferred' in r for r in results))
                    return {'content':'','tool_calls':[tc('complete_task',{'summary':'verified 7415'})]}
                def execute(name,args,context):
                    if name=='read_file':return {'success':True,'output':'Verified source number is 7415'}
                    self.assertEqual(args['summary'],'verified 7415')
                    return {'success':True,'is_complete':True,'summary':args['summary']}
                with patch.object(session_manager,'LayeredMemory',Memory),patch.object(session_manager.model_bridge,'call_model_step',side_effect=model),patch.object(session_manager.tools_registry,'execute_tool',side_effect=execute),patch.object(session_manager.session_store,'get_session_metadata',return_value={'workspace':'.','max_steps':3}),patch.object(session_manager.session_store,'get_recent_messages',return_value=[]),patch.object(session_manager.session_store,'get_connection'),patch.object(session_manager.session_store,'set_session_status'),patch.object(session_manager.session_store,'save_message',side_effect=lambda sid,msg:saved.append(msg)),patch.object(session_manager.event_bus,'publish_event'),patch('extensions.prompt_catalog',return_value=''):
                    session_manager.SessionRunner('fixture','run','Read evidence.txt').run_loop()
                self.assertEqual(len(calls),2)
                self.assertIn('7415',saved[-1]['content']);self.assertNotIn('1111',saved[-1]['content'])


if __name__=='__main__':unittest.main()
