"""抽奖与人情分析引擎。

三个坚持（写进 README 的诚实条款）：

  1. **绝不编概率**。麦当劳 MCP 的 `query-lottery-info` 不返回奖品概率，
     任何想着 bekann的概率数字都是假的。本项目只统计「奖品构成」。
  2. **能不能抽听服务端的**。`drawDecision.resourceEligible` 是唯一真相，
     绝不根据 `availableTimes` 是否为 0 自行推断（混合规则下 availableTimes=0
     仍可能能用积分抽）。
  3. **默认不抽**。`draw` 子命令必须先展示本次实际消耗，且要显式 `--confirm`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 归一化
# --------------------------------------------------------------------------- #
def _num(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class LotterySnapshot:
    """一次 query-lottery-info 的结构化视图。"""

    raw: Dict[str, Any]
    activity_code: str = ""
    activity_name: str = ""
    status_text: str = ""
    begin_time: str = ""
    end_time: str = ""
    draw_point: Optional[float] = None
    draw_type_text: str = ""
    available_times: Optional[int] = None
    available_point: Optional[float] = None
    eligible: Optional[bool] = None
    reason: str = ""
    next_consumption: Dict[str, Any] = None
    fallback_consumption: Dict[str, Any] = None
    prizes: List[Dict[str, Any]] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "LotterySnapshot":
        raw = raw or {}
        # 兼容两种形态：已拆壳的业务对象，或 {"success":..,"data":{...}} 信封
        if "data" in raw and isinstance(raw["data"], dict):
            raw = raw["data"]
        decision = raw.get("drawDecision") or {}
        return cls(
            raw=raw,
            activity_code=str(raw.get("activityCode") or ""),
            activity_name=str(raw.get("activityName") or ""),
            status_text=str(raw.get("activityStatusText") or ""),
            begin_time=str(raw.get("beginTime") or ""),
            end_time=str(raw.get("endTime") or ""),
            draw_point=_num(raw.get("drawPoint")),
            draw_type_text=str(raw.get("drawTypeText") or ""),
            available_times=_num(raw.get("availableTimes")) and int(_num(raw.get("availableTimes"))),
            available_point=_num(raw.get("availablePoint")),
            eligible=decision.get("resourceEligible"),
            reason=str(decision.get("reason") or ""),
            next_consumption=decision.get("nextConsumption") or {},
            fallback_consumption=decision.get("fallbackConsumption"),
            prizes=raw.get("prizes") or [],
        )

    @property
    def is_open(self) -> bool:
        return self.status_text == "进行中"


# --------------------------------------------------------------------------- #
# 分析
# --------------------------------------------------------------------------- #
def draw_readiness(snap: LotterySnapshot) -> Dict[str, Any]:
    """这次到底能不能抽，还差多少。"""
    need = snap.draw_point
    have = snap.available_point
    gap = None
    if need is not None and have is not None:
        gap = round(need - have, 1)
    return {
        "activityName": snap.activity_name,
        "statusText": snap.status_text,
        "activityWindow": "%s ~ %s" % (snap.begin_time, snap.end_time),
        "drawPoint": need,
        "drawTypeText": snap.draw_type_text,
        "availablePoint": have,
        "availableTimes": snap.available_times,
        "serverDecision": {
            "resourceEligible": snap.eligible,
            "reason": snap.reason or None,
            "nextConsumption": snap.next_consumption.get("text")
            if snap.next_consumption else None,
            "fallback": snap.fallback_consumption,
        },
        "gapPoint": gap if (gap is not None and gap > 0) else 0,
        "verdict": _verdict_text(snap, gap),
    }


def _verdict_text(snap: LotterySnapshot, gap) -> str:
    if not snap.is_open:
        return "活动当前非进行中（%s），暂不可参与" % snap.status_text
    if snap.eligible is True:
        return "✅ 服务端判定资源充足，本次可以抽"
    if snap.eligible is False:
        return "⛔ 服务端判定不可抽（%s），还需 %.1f 积分" % (
            snap.reason or "资源不足", gap or 0)
    return "❓ 服务端未给出明确判定，请以 drawDecision 为准"


def prize_pool(snap: LotterySnapshot) -> Dict[str, Any]:
    """按奖品类型聚合。**不输出任何概率**。"""
    buckets: Dict[str, List[str]] = {}
    for p in snap.prizes:
        t = str(p.get("typeText") or "未分类")
        buckets.setdefault(t, []).append(str(p.get("name") or "未知奖品"))
    return {
        "total": len(snap.prizes),
        "buckets": {k: {"count": len(v), "items": v} for k, v in buckets.items()},
        "probabilityDisclosed": False,
        "note": "麦当劳 MCP 未公开各奖品中奖概率，本项目不推测、不估算概率。",
    }


def categorize_prize(name: str) -> str:
    """对奖品名做粗分类，用于「值不值得攒」的参考，同样不涉及金额承诺。"""
    n = str(name)
    if "券" in n:
        if "折" in n or "立减" in n:
            return "折扣/立减券"
        return "优惠券"
    if "积分" in n:
        return "返积分"
    if any(k in n for k in ("玩具", "周边", "公仔", "包", "杯", "帽")):
        return "实物周边"
    return "其他权益"


def point_plan(snap: LotterySnapshot, per_order_point: float = 10.0) -> Dict[str, Any]:
    """攒够一次抽奖还差多少：给出次数估算，并明确「估算依赖假设」。

    假设：每完成一笔有效订单约获得 per_order_point 积分（默认 10）。
    这是一个**可配置假设**，不是官方承诺，报告里必须写明。
    """
    gap = max(0.0, (snap.draw_point or 0) - (snap.available_point or 0))
    orders = None
    if per_order_point > 0:
        orders = -(-gap // per_order_point)  # 向上取整
    times_now = int((snap.available_point or 0) // (snap.draw_point or 1)) if snap.draw_point else 0
    return {
        "gapPoint": round(gap, 1),
        "assumedPointPerOrder": per_order_point,
        "estimatedOrders": int(orders) if orders is not None else None,
        "drawableNow": times_now,
        "assumptionNote": "「每单约得 %.0f 积分」为可配置的估算假设，实际积分规则以麦当劳官方为准。" % per_order_point,
    }


def summarize_my_prizes(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把 query-my-prizes 的结果按状态归堆，并挑出需要尽快用掉的。"""
    prizes = (raw or {}).get("prizes") or []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    urgent = []
    for p in prizes:
        st = str(p.get("statusText") or "未知状态")
        buckets.setdefault(st, []).append(p)
        remind = str(p.get("timeRemindText") or "")
        if any(k in remind for k in ("即将", "还剩", "今日", "明天", "过期")):
            urgent.append({"name": p.get("name"), "remind": remind})
    return {
        "total": len(prizes),
        "counts": {k: len(v) for k, v in buckets.items()},
        "recent": [
            {"name": p.get("name"), "status": p.get("statusText"),
             "time": p.get("recordTime"), "remind": p.get("timeRemindText")}
            for p in prizes[:8]
        ],
        "urgent": urgent,
        "hasMore": bool((raw or {}).get("hasMore")),
    }


def pick_point_related_campaigns(calendar_days: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从活动日历里挑出可能与积分相关的活动（名称/内容含积分语义词）。

    这是**关键词筛选**，不是官方标注，报告里会写明。
    """
    keys = ("积分", "会员", "APP专享", "抢先购", "兑换", "抽奖")
    found = []
    for day in calendar_days or []:
        date = str(day.get("date") or day.get("title") or "")
        for act in day.get("activities") or []:
            title = str(act.get("title") or "")
            desc = str(act.get("content") or act.get("desc") or "")
            blob = title + desc
            if any(k in blob for k in keys):
                found.append({
                    "date": date,
                    "title": title,
                    "matched": [k for k in keys if k in blob],
                })
    return found
