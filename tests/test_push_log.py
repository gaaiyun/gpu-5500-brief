import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import push_log


class PushLogTests(unittest.TestCase):
    def test_each_channel_sends_once_a_day(self):
        saved=(push_log.PATH,push_log.STATE,push_log.REPORTED)
        with tempfile.TemporaryDirectory() as tmp:
            push_log.PATH,push_log.STATE,push_log.REPORTED=Path(tmp)/"push_log.json",Path(tmp)/"state.json",Path(tmp)/"reported"
            push_log.STATE.write_text('{"date":"2026-10-31"}',encoding="utf-8")
            try:
                self.assertFalse(push_log.sent("dingtalk"))
                push_log.record("dingtalk")
                self.assertTrue(push_log.sent("dingtalk"))
                self.assertFalse(push_log.sent("pushplus"))
                push_log.PATH.write_text('{"dingtalk":"2020-01-01"}',encoding="utf-8")
                self.assertFalse(push_log.sent("dingtalk"))
                push_log.PATH.write_text("not json",encoding="utf-8")
                self.assertFalse(push_log.sent("dingtalk"))
            finally:
                push_log.PATH,push_log.STATE,push_log.REPORTED=saved

    def test_first_push_of_a_report_keeps_what_the_group_saw(self):
        saved=(push_log.PATH,push_log.STATE,push_log.REPORTED)
        with tempfile.TemporaryDirectory() as tmp:
            push_log.PATH,push_log.STATE,push_log.REPORTED=Path(tmp)/"push_log.json",Path(tmp)/"state.json",Path(tmp)/"reported"
            try:
                push_log.STATE.write_text('{"date":"2026-10-31","run":1}',encoding="utf-8")
                push_log.record("dingtalk")
                push_log.STATE.write_text('{"date":"2026-10-31","run":2}',encoding="utf-8")
                push_log.record("pushplus")
                self.assertEqual(push_log.last_report("2026-10-31")["run"],1)
                self.assertIsNone(push_log.last_report("2026-10-31",include_day=False))
                for n in range(1,15):
                    (push_log.REPORTED/f"2026-09-{n:02d}.json").write_text('{"date":"x"}',encoding="utf-8")
                push_log.prune()
                kept=sorted(p.stem for p in push_log.REPORTED.glob("*.json"))
                self.assertEqual(len(kept),push_log.KEEP_REPORTS)
                self.assertEqual(kept[-1],"2026-10-31")
            finally:
                push_log.PATH,push_log.STATE,push_log.REPORTED=saved


if __name__=="__main__":unittest.main()
