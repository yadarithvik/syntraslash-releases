"""Regression tests for observed desktop workflow failures; no input is injected."""
import sys, tempfile, os, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['SYNTRA_BASE_DIR']=tempfile.mkdtemp(prefix='syntra-regression-')
import tools_registry as tr, model_bridge as mb, session_manager as sm, desktop_coordinator as dc, session_store as store

class DesktopRegression(unittest.TestCase):
 def test_visible_mode_has_no_hidden_execution(self):
  names={t['function']['name'] for t in mb.get_tool_definitions('transparent')}
  self.assertIn('mouse_move',names)
  self.assertFalse(names & {'write_file','run_python','run_powershell','start_process'})
  for name in ('write_file','run_python','run_powershell','start_process'):
   self.assertFalse(tr.execute_tool(name,{}, {'mode':'transparent'})['success'])
 def test_focus_and_editor_guards(self):
  ctx={'mode':'transparent'}
  with patch.object(tr.perception,'get_foreground_window_info',return_value={'hwnd':22}), patch.object(tr.desktop_agent,'type_text') as type_mock:
   self.assertFalse(tr.execute_tool('type_text',{'text':'chocolate'},ctx)['success'])
   ctx.update(desktop_target={'hwnd':22},desktop_observed=True,focused_control={'editable':False})
   self.assertFalse(tr.execute_tool('type_text',{'text':'chocolate'},ctx)['success'])
   type_mock.assert_not_called()
   ctx['focused_control']={'editable':True}
   type_mock.return_value={'success':True,'output':'Typed'}
   with patch.object(dc.desktop_agent,'list_windows',return_value=[]),patch.object(dc.desktop_agent,'ensure_desktop'):
    self.assertTrue(tr.execute_tool('type_text',{'text':'test'},ctx)['success'])
   self.assertTrue(ctx['desktop_verification_pending'])
   self.assertFalse(tr.execute_tool('complete_task',{'summary':'done'},ctx)['success'])
 def test_wrong_window_inspection_cannot_erase_failed_typing(self):
  ctx={'mode':'transparent'}
  with patch.object(tr.perception,'get_foreground_window_info',return_value={'hwnd':10}):
   self.assertFalse(tr.execute_tool('type_text',{'text':'bad'},ctx)['success'])
  with patch.dict(tr.REGISTRY,{'inspect_ui':lambda args,ctx:{'success':True,'output':'different window'}}):
   self.assertTrue(tr.execute_tool('inspect_ui',{},ctx)['success'])
  self.assertFalse(tr.execute_tool('complete_task',{'summary':'fake success'},ctx)['success'])

 def test_nested_lease_retains_owner(self):
  with patch.object(dc.desktop_agent,'list_windows',return_value=[]),patch.object(dc.desktop_agent,'ensure_desktop'):
   with dc.desktop_lease('s','r'):
    with dc.desktop_lease('s','r'): pass
    self.assertEqual(dc.get_desktop_status()['owner']['run_id'],'r')
   self.assertIsNone(dc.get_desktop_status()['owner'])
 def test_tool_failure_is_observation_not_uncaught_exception(self):
  with patch.dict(tr.REGISTRY,{'test_error':lambda args,ctx:1/0}):
   ctx={}; result=tr.execute_tool('test_error',{},ctx)
   self.assertFalse(result['success']); self.assertTrue(ctx['last_tool_failed'])
 def run_fixture(self,responses):
  sid='fixture-'+str(id(responses)); store.create_session({'id':sid,'workspace':os.environ['SYNTRA_BASE_DIR'],'mode':'transparent','max_steps':5})
  inputs=[]
  def model(**kw):
   import copy
   inputs.append(copy.deepcopy(kw['messages']))
   return responses.pop(0)
  with patch.object(mb,'call_model_step',side_effect=model),patch.object(tr,'execute_tool',return_value={'success':True,'output':'verified','is_complete':True,'summary':'verified'}):
   sm.SessionRunner(sid,'fixture','perform visible task').run_loop()
  return store.get_session(sid),inputs
 def test_native_tool_history(self):
  # First observation is a non-completion, then completion.
  sid='history'; store.create_session({'id':sid,'workspace':os.environ['SYNTRA_BASE_DIR'],'mode':'background','max_steps':4})
  inputs=[]
  responses=[{'content':'','tool_calls':[{'function':{'name':'inspect_environment','arguments':{}}}]},{'content':'','tool_calls':[{'function':{'name':'complete_task','arguments':{'summary':'verified'}}}]}]
  def model(**kw):
   import copy
   inputs.append(copy.deepcopy(kw['messages'])); return responses.pop(0)
  with patch.object(mb,'call_model_step',side_effect=model),patch.object(tr,'execute_tool',side_effect=[{'success':True,'output':'observed'},{'success':True,'is_complete':True,'summary':'verified'}]):
   sm.SessionRunner(sid,'history','inspect environment').run_loop()
  self.assertEqual(store.get_session(sid)['status'],'completed')
  self.assertEqual(inputs[1][-1]['role'],'tool')
  self.assertIn('tool_calls',inputs[1][-2])
 def test_prose_tool_call_never_counts_as_success(self):
  replies=[{'content':'{"tool_call":"press_hotkey","args":{"keys":["enter"]}}','tool_calls':[]} for _ in range(3)]
  session,_=self.run_fixture(replies)
  self.assertEqual(session['status'],'failed')

if __name__=='__main__': unittest.main()
