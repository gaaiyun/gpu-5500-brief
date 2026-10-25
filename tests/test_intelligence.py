import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from intelligence import validate_ai


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.fact={'source_id':'test','title':'订单','summary':'计划产量可能不超过300万张','impact':'配额仍待确认','watch':'确认发货','date':'2026-10-25','url':'https://example.com'}
        self.item={'source_id':'test','summary':'计划产量可能不超过300万张','impact':'配额仍待确认','watch':'确认发货'}

    def test_new_numbers_rejected(self):
        with self.assertRaises(ValueError):validate_ai({'items':[dict(self.item,summary='确认产量400万张')]},[self.fact])

    def test_uncertainty_cannot_be_removed(self):
        with self.assertRaises(ValueError):validate_ai({'items':[dict(self.item,summary='计划产量不超过300万张')]},[self.fact])

    def test_wrong_source_rejected(self):
        with self.assertRaises(ValueError):validate_ai({'items':[dict(self.item,source_id='unknown')]},[self.fact])

    def test_traceable_summary_keeps_metadata(self):
        row=validate_ai({'items':[self.item]},[self.fact])[0]
        self.assertEqual(row['url'],'https://example.com')
        self.assertEqual(row['date'],'2026-10-25')


if __name__=='__main__':unittest.main()
