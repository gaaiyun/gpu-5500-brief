import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import push_log


class PushLogTests(unittest.TestCase):
    def test_each_channel_sends_once_a_day(self):
        saved=push_log.PATH
        with tempfile.TemporaryDirectory() as tmp:
            push_log.PATH=Path(tmp)/"push_log.json"
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
                push_log.PATH=saved


if __name__=="__main__":unittest.main()
