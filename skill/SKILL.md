---
name: mcd-prize-radar
description: 麦门抽奖情报局 —— 麦当劳积分抽奖的体检与情报工具。当用户问「我能抽奖吗」「还差多少积分」「抽奖有什么奖品」「我抽中的东西过期了吗」「怎么攒积分」时使用本 Skill。
---

# 麦门抽奖情报局

回答四个问题：**现在能不能抽 · 还差多少 · 奖池有什么 · 攒分路径在哪**。

## 命令

```bash
python -m src.cli check     # 抽奖体检：能否抽 / 差多少分
python -m src.cli pool      # 奖品池构成
python -m src.cli plan      # 攒够一次还要几单
python -m src.cli prizes    # 我的中奖记录与到期提醒
python -m src.cli events    # 日历里与积分相关的活动
python -m src.cli draw      # 抽奖（默认 dry_run）
```

## 硬约束（必须遵守）

1. **能不能抽只听服务端** `drawDecision.resourceEligible`，不要看 `availableTimes` 猜。
2. **绝不输出任何中奖概率**。官方未公开，猜出来就是误导。
3. **抽奖前必须先展示** `drawDecision.nextConsumption.text`，并得到用户明确确认后才可加 `--confirm`。
4. 服务端判定资源不足时**终止**，不要重试、不要绕过。
5. `plan` 的订单数必须说明是「假设每单约 N 积分」的估算。

## 表达风格

报具体数字 + 结论，不要说「差不多可以试试」。
例：「当前 9.9 积分，单次 24 分，还差 14.1 分，服务端判定不可抽。」
