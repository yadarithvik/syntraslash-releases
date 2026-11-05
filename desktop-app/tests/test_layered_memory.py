"""Durability, isolation, bounded recall, cancellation, and source integrity."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memory_engine import LayeredMemory, MemoryBudgetError, TokenBudget


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.mem=LayeredMemory(self.root,'A',hot_tokens=2048,recall_tokens=2048)

    def test_disk_persistence_after_new_instance(self):
        self.mem.record('first','user','HELIOTROPE database filename = heliotrope_7391.sqlite')
        reloaded=LayeredMemory(self.root,'A')
        self.assertIn('heliotrope_7391.sqlite',reloaded.search('HELIOTROPE database filename')[0]['excerpt'])

    def test_retrieve_old_middle_fact_from_large_history(self):
        for i in range(240):
            body=('Unrelated task iteration '+str(i)+'\n')*60
            if i==81:
                body+='\nHELIOTROPE database filename = heliotrope_7391.sqlite\n'
            self.mem.record('history:'+str(i),'user',body)
        result=self.mem.prepare([{'role':'system','content':'Use source evidence.'},
                                 {'role':'user','content':'What was the HELIOTROPE database filename?'}],
                                'What was the HELIOTROPE database filename?')
        self.assertIn('heliotrope_7391.sqlite',json.dumps(result))
        self.assertLess(self.mem.last_stats['hot_tokens'],2049)
        self.assertLess(self.mem.last_stats['recall_tokens'],2049)
        self.assertGreater(self.mem.status()['stored_characters'],300000)
        self.assertLess(len(json.dumps(result)),12000)

    def test_cross_session_isolation_and_query_syntax(self):
        other=LayeredMemory(self.root,'B')
        other.record('private','user','Private heliotrope passphrase = B_ONLY_991')
        self.assertEqual(self.mem.search('heliotrope " OR * ; DROP TABLE layers;'),[])
        self.assertEqual(other.status()['layers'],1)

    def test_recall_does_not_lose_fact_after_repetitive_prefix(self):
        prefix='Historical project note about unrelated visual refinements.\n'*40
        self.mem.record('fact','user',prefix+'HELIOTROPE approved database filename = heliotrope_7391.sqlite')
        found=self.mem.search('For project HELIOTROPE what database filename did we approve?')
        self.assertIn('heliotrope_7391.sqlite',found[0]['excerpt'])

    def test_concurrent_session_writes(self):
        def write(i):
            session=LayeredMemory(self.root,'session-'+str(i%4))
            session.record('record-'+str(i),'user','Canonical project key = value_'+str(i))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write,range(80)))
        for i in range(4):
            self.assertEqual(LayeredMemory(self.root,'session-'+str(i)).status()['layers'],20)

    def test_cancelled_record_is_rolled_back(self):
        self.mem.record('source','user','prior correct content')
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):
            self.mem.record('source','user','replacement'*1000,event)
        self.assertIn('prior correct',self.mem.search('prior correct')[0]['excerpt'])

    def test_unicode_chunks_are_lossless(self):
        text='తెలుగు 日本語 café 🦥 '*1200
        self.mem.record('unicode','user',text)
        with self.mem.connection() as db:
            parts=db.execute('SELECT content FROM layers WHERE source_key=? ORDER BY ordinal',('unicode',)).fetchall()
        self.assertEqual(''.join(x[0] for x in parts),text)
        self.assertTrue(all(len(x[0].encode('utf-8'))<=3072 for x in parts))

    def test_large_latest_request_fails_without_losing_source(self):
        with self.assertRaises(MemoryBudgetError):
            self.mem.prepare([{'role':'user','content':'very large request '*1000}],'very large request')
        self.assertGreater(self.mem.status()['layers'],0)

    def test_tool_pairs_remain_valid(self):
        calls=[{'id':'call1','function':{'name':'read_file','arguments':{'path':'x.py'}}}]
        messages=[{'role':'system','content':'Act using tools.'},{'role':'user','content':'Read x.py'},
                  {'role':'assistant','content':'','tool_calls':calls},
                  {'role':'tool','tool_name':'read_file','content':'database key = 331'}]
        result=self.mem.prepare(messages,'Read x.py')
        roles=[x['role'] for x in result if not x.get('_memory')]
        self.assertEqual(roles[-2:],['assistant','tool'])
        self.assertEqual(result[-2]['tool_calls'],calls)

    def test_oversized_tool_result_archived_before_reduction(self):
        messages=[{'role':'assistant','content':'','tool_calls':[{'function':{'name':'read_file','arguments':{}}}]},
                  {'role':'tool','tool_name':'read_file','content':'long output '*2000+' TARGET_X_331'}]
        result=self.mem.prepare(messages,'Investigate target')
        self.assertFalse(any(x['role']=='tool' for x in result))
        self.assertIn('TARGET_X_331',self.mem.search('TARGET_X_331')[0]['excerpt'])
        self.assertLessEqual(self.mem.last_stats['hot_tokens'],2048)

    def test_memory_evidence_is_not_rearchived(self):
        self.mem.record('earlier','user','project canonical name = heliotrope')
        messages=[{'role':'user','content':'What is heliotrope project name?'}]
        a=self.mem.prepare(messages,messages[0]['content'])
        count=self.mem.status()['layers']
        self.mem.prepare(a,messages[0]['content'])
        self.assertEqual(self.mem.status()['layers'],count)

    def test_bootstrap_streams_and_restarts_without_duplicate_import(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.execute('CREATE TABLE messages(id TEXT, session_id TEXT,role TEXT, content TEXT)')
        db.executemany('INSERT INTO messages VALUES(?,?,?,?)',[(str(i),'A','user','schema table = old_'+str(i)) for i in range(100)])
        self.mem.bootstrap(db)
        count=self.mem.status()['layers']
        self.mem.bootstrap(db)
        self.assertEqual(self.mem.status()['layers'],count)
        self.assertIn('old_42',self.mem.search('old_42')[0]['excerpt'])

    def test_dossier_distills_deduplicates_and_preserves_raw(self):
        self.mem.record('a','user','hello\nDatabase filename = copper.sqlite\nNext step: verify schema')
        self.mem.record('b','user','Database filename = copper.sqlite\nthanks')
        count=self.mem.status()['layers']
        result=self.mem.compact('Project')
        body=Path(result['path']).read_text(encoding='utf-8')
        self.assertEqual(body.count('Database filename = copper.sqlite'),1)
        self.assertNotIn('\n- hello',body)
        self.assertIn('Next step: verify schema',body)
        self.assertEqual(self.mem.status()['layers'],count)
        self.assertEqual(result['method'],'extractive')

    def test_dossier_size_cap_and_cancel_keep_previous_archive(self):
        for i in range(30):
            self.mem.record(str(i),'user',('schema field_'+str(i)+' = '+str(i))*200)
        result=self.mem.compact('Cap',max_bytes=2048)
        prior=Path(result['path']).read_bytes()
        self.assertLessEqual(len(prior),2048)
        self.assertTrue(result['truncated'])
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):
            self.mem.compact('Cancel',event)
        self.assertEqual(Path(result['path']).read_bytes(),prior)

    def test_token_budget_uses_actual_counter(self):
        budget=TokenBudget(lambda x:len(x.split()))
        self.assertEqual(budget.count('one two three'),3)
        self.assertLessEqual(budget.count(budget.fit('one two three four',2)),2)


if __name__=='__main__':
    unittest.main()
