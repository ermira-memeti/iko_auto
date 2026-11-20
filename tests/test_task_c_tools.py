"""Minimal boundaries for Task C ranking scores (no machine-learning models required)."""
import unittest,importlib.util
from pathlib import Path

p=Path(__file__).resolve().parents[1]/'reproduce'/'task_c'/'score_rankings.py'
spec=importlib.util.spec_from_file_location('task_c_scorer',p)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class TestTaskCScorer(unittest.TestCase):
    def test_all_known_direct_positive_at_rank_2(self):
        Q={('H1','q','a'):0,('H1','q','b'):2,('H1','q','c'):1}
        s=mod.score_one('H1','q',['a','b','c'],Q)
        self.assertEqual((s['hit5_lower'],s['hit5_upper']),(1,1))
        self.assertAlmostEqual(s['mrr5_lower'],0.5)
        self.assertEqual(s['unjudged_top5'],0)
        self.assertIsNotNone(s['ndcg5_pool_relative_if_complete'])
    def test_unknown_candidate_is_not_grade_zero(self):
        Q={('H1','q','a'):0,('H1','q','b'):2}
        s=mod.score_one('H1','q',['x','a','b'],Q)
        self.assertEqual((s['hit5_lower'],s['hit5_upper']),(1,1))
        self.assertAlmostEqual(s['mrr5_lower'],1/3)
        self.assertAlmostEqual(s['mrr5_upper'],1.0)
        self.assertIsNone(s['ndcg5_pool_relative_if_complete'])
    def test_all_unjudged_hit_bounds(self):
        s=mod.score_one('Development','q',['new'],{})
        self.assertEqual((s['hit5_lower'],s['hit5_upper']),(0,1))
        self.assertIsNone(s['ndcg5_pool_relative_if_complete'])

if __name__=='__main__':unittest.main()
