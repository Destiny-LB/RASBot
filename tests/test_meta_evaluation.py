import tempfile
import unittest
import json
from pathlib import Path
from rasbot.meta_evaluation import evaluate, weighted, WEIGHTS, compare


class MetaTests(unittest.TestCase):
    def test_missing_weights_never_renormalize(self):
        m={k:1.0 for k in WEIGHTS};m['risk_coverage']=None
        q=weighted(m)
        self.assertIsNone(q['score']);self.assertEqual(q['measured_points'],70)
        self.assertEqual(q['possible_range'],[70,100])

    def test_duplicates_are_metric_not_validity_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'01_generate/submission';p.mkdir(parents=True)
            (p/'test_suite.json').write_text(json.dumps([{'id':i,'inputs':[{'shape':[1]}]} for i in range(4)]))
            task={'state':'validation_failed','result':{'workspace':tmp,'validation':{'passed':False,'reason':'Duplicate input specifications'}},'events':[]}
            report=evaluate(task)
            self.assertEqual(report['quality']['metrics']['diversity'],.25)
            self.assertNotEqual(report['validity']['eligible'],False)
            self.assertFalse(report['promotion_eligible'])
            self.assertEqual(task['state'],'validation_failed')

    def test_missing_suite_is_quality_failure_not_tampering(self):
        r=evaluate({'state':'validation_failed','result':{},'events':[]})
        self.assertEqual(r['quality']['metrics']['valid_rules'],0)
        self.assertIsNone(r['validity']['eligible'])

    def test_compare_only_common_measured_metrics(self):
        a={'quality':weighted(dict.fromkeys(WEIGHTS))}
        b={'quality':weighted({k:1 for k in WEIGHTS})}
        r=compare([('task',a,b)])
        self.assertEqual(r['pairs'][0]['common_weight'],0)
        self.assertEqual(r['decision'],'not_for_promotion')
