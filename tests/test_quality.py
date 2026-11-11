import copy
import unittest
from rasbot.quality import diversity


class DiversityCalibration(unittest.TestCase):
    def case(self, shape=17, dtype='fp32'):
        return {'id':0,'inputs':[{'name':'x','shape':[shape],'dtype':dtype,'range_values':[0,1]}],
                'generate_intent':'tail boundary', 'trigger_library_ref':['TRIGGER-1: tail']}

    def test_renaming_and_narrative_cannot_hide_duplicate(self):
        a=self.case();b=copy.deepcopy(a);b.update(id=99,generate_intent='different story',trigger_library_ref=[])
        self.assertEqual(diversity([a,b])['duplicate_excess'],1)

    def test_distinct_shapes_and_dtype_are_retained(self):
        r=diversity([self.case(),self.case(18),self.case(17,'fp16')])
        self.assertEqual(r['duplicate_excess'],0)
        self.assertEqual(r['shape_signatures'],2)
        self.assertEqual(r['dtype_signatures'],2)

    def test_key_order_is_irrelevant(self):
        a=self.case();b=dict(reversed(list(a.items())))
        self.assertEqual(diversity([a,b])['unique_specifications'],1)

    def test_other_semantic_fields_not_discarded(self):
        a=self.case();b=copy.deepcopy(a);b['outputs']=[{'dtype':'fp16'}]
        self.assertEqual(diversity([a,b])['duplicate_excess'],0)

    def test_malformed_and_empty_are_not_perfect_scores(self):
        for s in ([],{},[{}],[{'inputs':[None]}]):
            self.assertEqual(diversity(s)['status'],'invalid')

    def test_semantic_wrongness_is_not_claimed_detected(self):
        r=diversity([self.case(16)])
        self.assertEqual(r['status'],'observed')
        self.assertFalse(r['promotion_eligible'])
        self.assertIn('not sampled',r['scope'])
