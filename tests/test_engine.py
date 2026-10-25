"""单元测试：全部离线，不需要 Token。"""

import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "src"))

from cli import parse_calendar_text  # noqa: E402
from prize_engine import (LotterySnapshot, categorize_prize, draw_readiness,  # noqa: E402
                          pick_point_related_campaigns, point_plan, prize_pool,
                          summarize_my_prizes)

SAMPLE = os.path.join(BASE, "samples", "lottery_sample.json")
SAMPLE_PRIZES = os.path.join(BASE, "samples", "prizes_sample.json")


def load_lottery():
    with open(SAMPLE, "r", encoding="utf-8") as fh:
        return LotterySnapshot.from_raw(json.load(fh)["data"])


class SnapshotTest(unittest.TestCase):
    def test_fields_parsed(self):
        s = load_lottery()
        self.assertEqual(s.activity_code, "dtx2")
        self.assertEqual(s.activity_name, "麦麦积分抽奖")
        self.assertEqual(s.draw_point, 24.0)
        self.assertEqual(s.available_point, 9.9)
        self.assertFalse(s.eligible)
        self.assertEqual(s.reason, "积分不足")
        self.assertEqual(len(s.prizes), 10)

    def test_is_open(self):
        self.assertTrue(load_lottery().is_open)
        empty = LotterySnapshot.from_raw({})
        self.assertFalse(empty.is_open)


class ReadinessTest(unittest.TestCase):
    def test_gap_computed(self):
        info = draw_readiness(load_lottery())
        self.assertAlmostEqual(info["gapPoint"], 14.1, places=1)
        self.assertFalse(info["serverDecision"]["resourceEligible"])
        self.assertIn("不可抽", info["verdict"])

    def test_eligible_case(self):
        raw = load_lottery().raw
        raw["availablePoint"] = "100"
        raw["drawDecision"]["resourceEligible"] = True
        raw["drawDecision"]["reason"] = None
        info = draw_readiness(LotterySnapshot.from_raw(raw))
        self.assertEqual(info["gapPoint"], 0)
        self.assertIn("可以抽", info["verdict"])

    def test_never_infer_from_available_times(self):
        """availableTimes=0 时也必须听服务端的判定。"""
        raw = load_lottery().raw
        raw["availableTimes"] = 0
        raw["drawDecision"]["resourceEligible"] = True
        info = draw_readiness(LotterySnapshot.from_raw(raw))
        self.assertIn("可以抽", info["verdict"])

    def test_closed_activity(self):
        raw = load_lottery().raw
        raw["activityStatusText"] = "已结束"
        info = draw_readiness(LotterySnapshot.from_raw(raw))
        self.assertIn("非进行中", info["verdict"])


class PoolTest(unittest.TestCase):
    def test_no_probability_ever(self):
        pool = prize_pool(load_lottery())
        self.assertEqual(pool["total"], 10)
        self.assertFalse(pool["probabilityDisclosed"])
        self.assertIn("概率", pool["note"])
        blob = json.dumps(pool, ensure_ascii=False)
        self.assertNotIn("%", blob.split("probabilityDisclosed")[0].replace("5折", "").replace("5.5折", "").replace("6折", ""))

    def test_buckets_sum(self):
        pool = prize_pool(load_lottery())
        self.assertEqual(sum(b["count"] for b in pool["buckets"].values()), pool["total"])

    def test_categorize(self):
        self.assertEqual(categorize_prize("麦辣三件套5折券"), "折扣/立减券")
        self.assertEqual(categorize_prize("30积分"), "返积分")
        self.assertEqual(categorize_prize("未知好物"), "其他权益")


class PlanTest(unittest.TestCase):
    def test_gap_and_orders(self):
        plan = point_plan(load_lottery(), per_order_point=10.0)
        self.assertAlmostEqual(plan["gapPoint"], 14.1, places=1)
        self.assertEqual(plan["estimatedOrders"], 2)
        self.assertEqual(plan["drawableNow"], 0)

    def test_assumption_disclosed(self):
        self.assertIn("假设", point_plan(load_lottery())["assumptionNote"])


class MyPrizesTest(unittest.TestCase):
    def test_empty_is_not_failure(self):
        with open(SAMPLE_PRIZES, "r", encoding="utf-8") as fh:
            summary = summarize_my_prizes(json.load(fh)["data"])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["counts"], {})

    def test_with_data(self):
        raw = {"prizes": [
            {"name": "麦旋风5折券", "statusText": "可用", "recordTime": "2026-10-20", "timeRemindText": "即将过期"},
            {"name": "30积分", "statusText": "已使用", "recordTime": "2026-09-01", "timeRemindText": ""},
        ], "hasMore": False}
        summary = summarize_my_prizes(raw)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["counts"]["可用"], 1)
        self.assertEqual(len(summary["urgent"]), 1)


class CalendarTest(unittest.TestCase):
    TEXT = """### 当前时间：2026-10-25

#### 2026年10月25日 今日

-   **活动标题**：-app专享积分抢先购
    **活动内容介绍**：APP专享积分抢先购10:40开抢
    <img src="http://x.jpg">

#### 2026年10月26日

-   **活动标题**：普通新品
    **活动内容介绍**：11.9元轻松get
"""

    def test_parse(self):
        days = parse_calendar_text(self.TEXT)
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["date"], "2026年10月25日 今日")
        self.assertEqual(len(days[0]["activities"]), 1)

    def test_pick_point_related(self):
        days = parse_calendar_text(self.TEXT)
        hits = pick_point_related_campaigns(days)
        self.assertEqual(len(hits), 1)
        self.assertIn("积分", hits[0]["matched"])

    def test_empty_input_safe(self):
        self.assertEqual(parse_calendar_text(""), [])
        self.assertEqual(parse_calendar_text(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
