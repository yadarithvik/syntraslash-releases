"""Offline packaged-runtime checks; never opens or controls other applications."""
from pathlib import Path
import hashlib
import json
import tempfile
import time
from memory_engine import LayeredMemory

VERSION='1.2.0-memory-preview'


def verify_memory(report_path):
    report_path=Path(report_path).resolve()
    report_path.parent.mkdir(parents=True,exist_ok=True)
    checks={}
    try:
        with tempfile.TemporaryDirectory(prefix='syntra-packaged-memory-') as directory:
            mem=LayeredMemory(directory,'packaged')
            for i in range(120):
                text=('Historical project note about unrelated interface changes.\n')*40
                if i==39:
                    text+='\nORCHID approved database filename = orchid_5827.sqlite\n'
                mem.record('history-'+str(i),'user',text)
            reopened=LayeredMemory(directory,'packaged')
            prompt=reopened.prepare([{'role':'user','content':'What database filename was approved for ORCHID?'}],
                                    'What database filename was approved for ORCHID?')
            checks['persistent_old_fact_recalled']='orchid_5827.sqlite' in json.dumps(prompt)
            checks['hot_budget_bounded']=reopened.last_stats['hot_tokens']<=2048
            checks['recall_budget_bounded']=reopened.last_stats['recall_tokens']<=2048
            checks['session_isolation']=not LayeredMemory(directory,'other').search('ORCHID')
            dossier=reopened.compact('Packaged verification')
            checks['dossier_saved']=Path(dossier['path']).is_file()
            checks['dossier_checksum']=hashlib.sha256(Path(dossier['path']).read_bytes()).hexdigest()==dossier['sha256']
            report={'version':VERSION,'passed':all(checks.values()),'checks':checks,
                    'memory_stats':reopened.status(),'timestamp':time.time()}
    except Exception as error:
        report={'version':VERSION,'passed':False,'checks':checks,'error':str(error)}
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1
