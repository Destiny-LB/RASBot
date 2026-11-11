import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from rasbot.core import Store
from rasbot.evaluation_audit import audit


class AuditTests(unittest.TestCase):
    def test_snapshot_is_read_only_and_detects_tampered_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root/'data')
            version=store.version({'name':'baseline'})
            identity=store.create('precision','fixture',version)
            ws=store.root/'runs'/identity
            suite=ws/'01_generate/submission/test_suite.json';suite.parent.mkdir(parents=True)
            suite.write_text(json.dumps([{'id':0,'inputs':[{'shape':[17]}], 'generate_intent':'tail', 'trigger_library_ref':['TRIGGER-1: tail']}]))
            ledger=ws/'01_generate/report/trigger_coverage.json';ledger.parent.mkdir()
            ledger.write_text(json.dumps({'triggers':[{'id':'1','status':'applicable','actual_case_ids':[0]}]}))
            materialized=ws/'input.json';materialized.write_text('[]')
            store.transition(identity,'queued','generated',{'workspace':str(ws),'validation':{
                'suite':str(suite),'suite_sha256':'wrong', 'atk_input':str(materialized),
                'atk_input_sha256':hashlib.sha256(materialized.read_bytes()).hexdigest()}})
            before=store.get(identity)
            report=audit(store.root,root/'audit')
            self.assertFalse(report['tasks'][0]['integrity']['suite']['matches_recorded_hash'])
            self.assertTrue(report['tasks'][0]['integrity']['atk_input']['matches_recorded_hash'])
            self.assertEqual(store.get(identity),before)
            self.assertEqual((root/'audit/artifacts'/identity/'suite.json').read_bytes(),suite.read_bytes())
            with self.assertRaises(FileExistsError):audit(store.root,root/'audit')
