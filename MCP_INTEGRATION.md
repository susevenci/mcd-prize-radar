# MCP_INTEGRATION.md

## 1. 接入方式

| 项目 | 值 |
|---|---|
| MCP Server | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 传输 | Streamable HTTP，JSON-RPC 2.0（兼容 SSE） |
| Endpoint | `https://mcp.mcd.cn` |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 客户端 | `src/mcp_client.py`（纯标准库，节流 300 次/分钟 + 429 退避） |

## 2. Tool 清单与调用映射

| Tool | 命令 | 关键字段 |
|---|---|---|
| `query-lottery-info` | `check` / `pool` / `plan` / `draw` | `activityCode`、`activityStatusText`、`drawPoint`、`drawTypeText`、`availablePoint`、`drawDecision.resourceEligible`、`drawDecision.nextConsumption`、`prizes[]` |
| `query-my-account` | `selfcheck` 连通性校验 | `availablePoint` |
| `query-my-prizes` | `prizes` | `prizes[].{name,statusText,recordTime,timeRemindText}`、`hasMore` |
| `campaign-calendar` | `events` | Markdown 文本，解析见 §4 |
| `draw-lottery` | `draw --confirm` | 唯一写操作，默认禁用 |

## 3. 核心流程（`check`）

```
tools/call query-lottery-info
        │
        ▼
LotterySnapshot.from_raw()   ← 结构化，保留 raw 便于追溯
        │
        ├── draw_readiness()   ← 读 drawDecision.resourceEligible（唯一真相）
        │                         └── gap = drawPoint - availablePoint
        ├── prize_pool()       ← 按 typeText 聚合，**不产生任何概率**
        └── point_plan()       ← 显式假设下的订单数估算
```

## 4. 为什么 `drawDecision` 是唯一真相

工具契约明确：混合消耗规则下可能出现 `availableTimes=0` 但 `nextConsumption.type=POINTS`，
即**仍可使用积分抽奖**。若自行用 `availableTimes` 推断，会把明明能抽的用户挡在门外。

因此本项目：

* 判定只读 `drawDecision.resourceEligible` 与 `reason`；
* `draw` 前必打印 `drawDecision.nextConsumption.text`；
* 服务端判定不足时**终止而非重试**，不绕过。
* 有专项单测守住这条：`test_never_infer_from_available_times`。

## 5. `campaign-calendar` 的文本解析

该工具返回渲染好的 Markdown（非 JSON），形态：

```
#### 2026年10月25日 今日

-   **活动标题**：xxx
    **活动内容介绍**：多行文案
    <img src="...">
```

`src/cli.py::parse_calendar_text` 按 `####` 切分日期、按 `**活动标题**` / `**活动内容介绍**` 提取字段，
自动跳过 `<img>` 行，并对「-」后多个空格做容错。

## 6. 业务价值

1. 把「能不能抽」从**尝试后失败**提前到**调用前就明确**；
2. 把抽奖决策所需的全部事实（单次消耗 / 当前积分 / 缺口 / 服务端判定）压到一屏；
3. 以代码约束落实官方工具契约，避免 Agent 误触发抽奖；
4. 不编概率，保证所有输出可被验证。

## 7. 配置示例

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

仓库内不含任何真实 Token。

## 附：接口实测留痕

本项目在 2026-10-25 对麦当劳 MCP 做过真实调用，完整记录（含当时账号状态、原始输出、复现命令）
见 docs/2026-10-25-实测记录.md。

实测确认的两个关键形态（代码已适配）：
1. 响应统一为 {"success":..,"code":..,"data":<业务数据>} 信封，业务数据在 data 内；
2. structuredContent 与 content[0].text 并存，客户端优先取 structuredContent。
