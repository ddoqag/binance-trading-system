# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

这是一个**高频交易（HFT）延迟队列强化学习系统**原型，采用 Go + Python 混合架构设计。代码库包含从基础原型到完整系统的渐进式开发阶段，最终实现了交易所级别的撮合引擎、SAC 强化学习智能体、以及币安实时数据流集成。

## File Structure

文件命名表示开发迭代版本（从早到晚）：

| 文件 | 说明 |
|------|------|
| `hft_latency_queue_rl_system_go_python.py` | 最简原型：基础 RL 智能体 + 撮合引擎 |
| `(2).py` → `(7).py` | 渐进增强版本 |
| `(7).py` | **最终完整版本**：包含所有功能模块 |
| `总纲.txt` | 系统架构设计文档（中文） |
| `新文件5.txt` ~ `新文件10.txt` | 量化交易架构设计补充文档 |

## Architecture

### Core Components (in v7)

```
┌─────────────────────────────────────────────────────────────┐
│                    HFT Latency Queue RL System              │
├─────────────────────────────────────────────────────────────┤
│  1. MatchingEngine       - 交易所级撮合引擎（FIFO队列）      │
│  2. TradingEnv           - Gym 风格 RL 环境                  │
│  3. SACAgent             - Soft Actor-Critic 智能体          │
│  4. BinanceL2Feed        - L2 深度数据 WebSocket 连接        │
│  5. BinanceTradeFeed     - 实时成交数据流                    │
│  6. ShadowQueueTracker   - 影子订单队列位置跟踪              │
│  7. FeatureEngine        - 特征工程（OFI/Trade Flow/Spread） │
│  8. LatencyEngine        - 延迟模拟引擎                      │
└─────────────────────────────────────────────────────────────┘
```

### State Space (4-5 dims)
- `OFI` - Order Flow Imbalance（订单流不平衡）
- `QueueRatio` - 队列位置比率
- `PriceDrift` - 价格漂移
- `Spread` - 买卖价差
- `TradeFlow` - 成交流（v7 新增）

### Action Space (Continuous)
- `action > 0.5` → Market Buy
- `action < -0.5` → Market Sell
- `-0.5 <= action <= 0.5` → Passive Limit Order

## Commands

### Run Latest Version
```bash
python "hft_latency_queue_rl_system_go_python (7).py"
```

### Run with Live Binance Data
```python
# 取消文件末尾注释：
# asyncio.run(run_full_system())
```

### Dependencies
```bash
pip install numpy torch gym websockets asyncio
```

## Key Design Patterns

### 1. Shadow Queue Tracking
追踪订单在 FIFO 队列中的相对位置，计算 `size_ahead / total` 作为状态输入：
```python
class ShadowQueueTracker:
    def get_queue_ratio(self, order_id) -> float:
        # 返回 0-1 之间的队列位置比率
```

### 2. Latency-Aware Execution
订单提交后进入延迟队列，模拟真实网络延迟：
```python
class LatencyEngine:
    def submit_order(self, order):
        delay = np.random.normal(base_latency, jitter)
        # 订单在 delay 后才到达交易所
```

### 3. Matching Engine with Hidden Liquidity
模拟真实订单簿，包含可见队列和隐藏流动性：
```python
class PriceLevel:
    queue: deque           # FIFO 可见订单队列
    hidden_liquidity: float # 隐藏流动性（暗池效应）
```

### 4. SAC Agent Architecture
- Twin Critics (Double Q-learning)
- Entropy regularization (temperature auto-tuning)
- Soft target updates (tau=0.005)

## Data Flow

```
Binance L2 WebSocket → BinanceL2Feed → FeatureEngine
                                              ↓
Binance Trade Stream → BinanceTradeFeed → FeatureEngine
                                              ↓
                                         TradingEnv
                                              ↓
                    State ←── [OFI, TradeFlow, Drift, Spread, QueueRatio]
                                              ↓
                                         SACAgent (decision)
                                              ↓
                    Action → LatencyEngine → MatchingEngine
```

## Important Notes

1. **文件名编码**：部分文件名包含中文和空格，在 Windows PowerShell 中需要用引号包裹

2. **实盘警告**：代码包含 Binance WebSocket 连接，但默认不执行真实交易。启用实盘前需：
   - 添加 API 密钥管理
   - 实现正式订单执行逻辑
   - 完善风险控制（Kill Switch）

3. **训练模式**：当前代码包含硬编码的训练循环，运行时会执行 50 个 episode 的训练

4. **Go 代码**：文件中包含注释掉的 Go 代码示例（`package main` 部分），作为未来 Go 执行引擎的参考

## Development Roadmap (from 总纲.txt)

根据架构文档，完整系统需要实现：

1. **模块 1**：微秒级通信层（Shared Memory / mmap）- Go/Python 共享内存
2. **模块 2**：核心执行引擎（Go HFT Engine）- Maker/Taker 决策、风控、状态机
3. **模块 3**：强化学习智能体（Python RL Agent）- 已部分实现
4. **模块 4**：实盘系统与容灾 - WAL、自动重连、降级策略
