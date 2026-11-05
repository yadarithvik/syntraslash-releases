import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model_bridge as bridge

class ContextEnvelopeTests(unittest.TestCase):
    def test_tools_and_template_are_counted(self):
        tools=[{'type':'function','function':{'name':'probe','parameters':{'type':'object'}}}]
        seen=[]
        def runtime(path,payload):
            seen.append((path,payload))
            return {'prompt':'rendered with tools'} if path=='/apply-template' else {'tokens':list(range(70))}
        with patch.object(bridge,'_runtime_json',side_effect=runtime):
            self.assertEqual(bridge.validate_context_payload({'messages':[{'role':'user','content':'test'}],'tools':tools,'max_tokens':2048}),70)
        self.assertEqual(seen[0][1]['tools'],tools)
        self.assertEqual(seen[1][1]['content'],'rendered with tools')

    def test_output_and_overhead_reserved(self):
        def runtime(path,payload):
            return {'prompt':'large'} if path=='/apply-template' else {'tokens':[1]*15000}
        with patch.object(bridge,'_runtime_json',side_effect=runtime),self.assertRaisesRegex(ValueError,'Context budget exceeded'):
            bridge.validate_context_payload({'messages':[],'max_tokens':2048})

    def test_unavailable_tokenizer_fails_before_generation(self):
        with patch.object(bridge,'_runtime_json',side_effect=OSError('offline')),self.assertRaisesRegex(RuntimeError,'Unable to verify'):
            bridge.validate_context_payload({'messages':[]})

    def test_native_tool_protocol_has_matching_ids(self):
        messages=[{'role':'assistant','content':'','tool_calls':[{'id':'abc','function':{'name':'recall_memory','arguments':{'query':'copper'}}}]},
                  {'role':'tool','tool_name':'recall_memory','content':'result'}]
        wire=bridge._completion_messages(messages)
        self.assertEqual(wire[0]['tool_calls'][0]['id'],wire[1]['tool_call_id'])
        self.assertEqual(wire[1]['content'],'result')

if __name__=='__main__': unittest.main()
