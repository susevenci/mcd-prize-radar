"""mcd-prize-radar 命令行入口。

零依赖；没有 Token 也能用 `--offline` 跑通全部分析逻辑。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_client import McpError, McdMcpClient  # noqa: E402
from prize_engine import (LotterySnapshot, categorize_prize, draw_readiness,  # noqa: E402
                          pick_point_related_campaigns, point_plan, prize_pool,
                          summarize_my_prizes)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_LOTTERY = os.path.join(BASE, "samples", "lottery_sample.json")
SAMPLE_PRIZES = os.path.join(BASE, "samples", "prizes_sample.json")


# --------------------------------------------------------------------------- #
# 数据获取
# --------------------------------------------------------------------------- #
def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_lottery(offline: bool):
    if not offline:
        try:
            raw = McdMcpClient.from_env().call_tool("query-lottery-info")
            if isinstance(raw, dict) and (raw.get("prizes") or raw.get("activityCode")
                                          or (raw.get("data") or {}).get("activityCode")):
                return LotterySnapshot.from_raw(raw), "麦当劳 MCP query-lottery-info 实时返回"
            print("[warn] 实时返回为空，回落本地快照", file=sys.stderr)
        except McpError as exc:
            print("[warn] MCP 调用失败，回落本地快照：%s" % exc, file=sys.stderr)
    data = _load_json(SAMPLE_LOTTERY)
    return LotterySnapshot.from_raw(data["data"]), "本地快照 %s" % os.path.basename(SAMPLE_LOTTERY)


def get_prizes(offline: bool, page=1, size=20):
    if not offline:
        try:
            raw = McdMcpClient.from_env().call_tool(
                "query-my-prizes", {"pageNum": str(page), "pageSize": str(size)})
            if isinstance(raw, dict):
                if isinstance(raw.get("data"), dict):
                    raw = raw["data"]
                return raw, "麦当劳 MCP query-my-prizes 实时返回"
        except McpError as exc:
            print("[warn] MCP 调用失败，回落本地样例：%s" % exc, file=sys.stderr)
    return _load_json(SAMPLE_PRIZES)["data"], "本地样例 %s" % os.path.basename(SAMPLE_PRIZES)


def parse_calendar_text(text: str):
    """解析 campaign-calendar 返回的 Markdown 文本。

    形态：
        #### 2026年10月25日 今日
        - **活动标题**：xxx
          **活动内容介绍**：多行文案…
    """
    days, day, act, mode = [], None, None, None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("####"):
            day = {"date": s.lstrip("# ").strip(), "activities": []}
            days.append(day)
            act = None
            continue
        # 容错：服务端可能写成 "- **活动标题**：" 或 "-   **活动标题**："
        if s.lstrip("- ").startswith("**活动标题**："):
            act = {"title": s.split("：", 1)[1].strip(), "content": ""}
            if day is not None:
                day["activities"].append(act)
            mode = "title"
            continue
        if s.startswith("**活动内容介绍**："):
            mode = "content"
            if act is not None:
                act["content"] = s.split("：", 1)[1].strip()
            continue
        if s.startswith("<img") or not s:
            continue
        if mode == "content" and act is not None and not s.startswith("-"):
            act["content"] += " " + s
    return days


def get_calendar(offline: bool):
    if not offline:
        try:
            raw = McdMcpClient.from_env().call_tool("campaign-calendar")
            text = raw.get("text") if isinstance(raw, dict) else json.dumps(raw, ensure_ascii=False)
            if text:
                return parse_calendar_text(text), "麦当劳 MCP campaign-calendar 实时返回"
        except McpError as exc:
            print("[warn] MCP 调用失败：%s" % exc, file=sys.stderr)
    return [], "离线模式无可用的日历数据"


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def cmd_selfcheck(_a):
    st = McdMcpClient.token_status()
    print("=== 环境自检 ===")
    print("MCD_MCP_TOKEN: %s" % ("已配置" if st["configured"] else "未配置"))
    print("tokenLength  : %d" % st["tokenLength"])
    print("endpoint     : %s" % st["endpoint"])
    print("结论：%s" % ("Token 已就绪" if st["configured"] else "未配置 Token，可用 --offline 体验"))
    return 0


def cmd_check(args):
    snap, note = get_lottery(args.offline)
    info = draw_readiness(snap)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print("【抽奖体检】%s" % info["activityName"])
    print("活动状态：%s（%s）" % (info["statusText"], info["activityWindow"]))
    print("消耗规则：%s｜单次需 %.0f 积分" % (info["drawTypeText"], info["drawPoint"] or 0))
    print("当前可用积分：%.1f" % (info["availablePoint"] or 0))
    print("服务端决策：resourceEligible=%s%s" % (
        info["serverDecision"]["resourceEligible"],
        "（%s）" % info["serverDecision"]["reason"] if info["serverDecision"]["reason"] else ""))
    if info["serverDecision"]["nextConsumption"]:
        print("本次实际消耗：%s" % info["serverDecision"]["nextConsumption"])
    print("结论：%s" % info["verdict"])
    if info["gapPoint"]:
        print("还差 %.1f 积分。" % info["gapPoint"])
    print("数据来源：%s" % note)
    return 0


def cmd_pool(args):
    snap, note = get_lottery(args.offline)
    pool = prize_pool(snap)
    if args.json:
        print(json.dumps(pool, ensure_ascii=False, indent=2))
        return 0
    print("【奖品池构成】共 %d 项" % pool["total"])
    for kind, body in pool["buckets"].items():
        print("  · %s（%d）" % (kind, body["count"]))
        for name in body["items"]:
            print("      - %s｜%s" % (name, categorize_prize(name)))
    print("\n%s" % pool["note"])
    print("数据来源：%s" % note)
    return 0


def cmd_plan(args):
    snap, note = get_lottery(args.offline)
    plan = point_plan(snap, per_order_point=args.per_order_point)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    print("【攒够一次抽奖】")
    print("距离下次抽奖还差：%.1f 积分" % plan["gapPoint"])
    print("当前立即可抽次数：%d" % plan["drawableNow"])
    if plan["estimatedOrders"] is not None:
        print("按假设每单 %.0f 积分估算，约需 %d 笔订单" % (
            plan["assumedPointPerOrder"], plan["estimatedOrders"]))
    print("⚠ %s" % plan["assumptionNote"])
    print("数据来源：%s" % note)
    return 0


def cmd_prizes(args):
    raw, note = get_prizes(args.offline)
    summary = summarize_my_prizes(raw)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print("【我的奖品】共 %d 件" % summary["total"])
    if not summary["total"]:
        print("  账号当前没有中奖记录 —— 这是真实空态，不代表查询失败。")
    for k, v in summary["counts"].items():
        print("  · %s：%d" % (k, v))
    for r in summary["recent"]:
        print("  - %s｜%s｜%s%s" % (r["name"], r["status"], r["time"],
                                   "｜%s" % r["remind"] if r["remind"] else ""))
    for u in summary["urgent"]:
        print("  ⏰ %s：%s" % (u["name"], u["remind"]))
    print("数据来源：%s" % note)
    return 0


def cmd_events(args):
    days, note = get_calendar(args.offline)
    hits = pick_point_related_campaigns(days)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0
    print("【可能与积分/会员相关的活动】共 %d 条" % len(hits))
    for h in hits[:args.top]:
        print("  · %s｜%s｜命中词：%s" % (h["date"], h["title"], "、".join(h["matched"])))
    print("\n⚠ 这是按活动标题/文案的**关键词筛选**，不等于官方标注，请以活动详情页为准。")
    print("数据来源：%s" % note)
    return 0


def cmd_draw(args):
    """抽奖：默认 dry_run，必须先看到消耗说明，且需显式 --confirm。"""
    snap, note = get_lottery(args.offline)
    info = draw_readiness(snap)
    print("【抽奖前置确认】")
    print("活动：%s（%s）" % (info["activityName"], info["statusText"]))
    print("本次实际消耗：%s" % (info["serverDecision"]["nextConsumption"] or "未知"))
    print("服务端判定：resourceEligible=%s" % info["serverDecision"]["resourceEligible"])
    if snap.eligible is False and not args.force:
        print("\n⛔ 服务端判定资源不足，已终止（不会发起抽奖）。")
        print("   如需继续请把积分攒够；本工具不会绕过服务端判定。")
        return 2
    if not args.confirm:
        print("\n未加 --confirm，dry_run 结束，未发起任何抽奖调用。")
        return 0
    if args.offline:
        print("\n离线快照模式不支持真实抽奖，请去掉 --offline。")
        return 2
    try:
        result = McdMcpClient.from_env().call_tool("draw-lottery")
    except McpError as exc:
        print("抽奖失败：%s" % exc, file=sys.stderr)
        return 1
    print("抽奖结果：%s" % json.dumps(result, ensure_ascii=False)[:800])
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="mcd-prize-radar",
                                description="麦门抽奖情报局：积分抽奖体检 · 奖品池盘点 · 攒分路径")
    sub = p.add_subparsers(dest="command")
    for name, fn, help_text in (("selfcheck", cmd_selfcheck, "Token 自检"),
                                ("check", cmd_check, "这次到底能不能抽"),
                                ("pool", cmd_pool, "奖品池构成（不含概率）"),
                                ("plan", cmd_plan, "还差多少分"),
                                ("prizes", cmd_prizes, "我的中奖记录"),
                                ("events", cmd_events, "日历里与积分相关的活动")):
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(func=fn)
        if name != "selfcheck":
            sp.add_argument("--offline", action="store_true")
            sp.add_argument("--json", action="store_true")
        if name == "plan":
            sp.add_argument("--per-order-point", type=float, default=10.0)
        if name == "events":
            sp.add_argument("--top", type=int, default=12)

    sp = sub.add_parser("draw", help="抽奖（默认 dry_run，需 --confirm）")
    sp.add_argument("--confirm", action="store_true", help="确认真实发起抽奖")
    sp.add_argument("--offline", action="store_true")
    sp.add_argument("--force", action="store_true", help="服务端判定不足时仍尝试（不推荐）")
    sp.set_defaults(func=cmd_draw)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
