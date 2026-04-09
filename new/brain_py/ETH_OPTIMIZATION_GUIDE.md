# ETH交易对优化指南

## 测试结果对比

| 指标 | BTCUSDT | ETHUSDT | 差距 |
|------|---------|---------|------|
| 点差 | 0.0014 bps | 0.0459 bps | **32倍** |
| 价格 | $70,000+ | $2,180 | 更适合小资金 |
| 流动性 | 极高 | 高 | 滑点可控 |

## ETH优势

1. **点差收益空间更大**: 32倍的点差提升意味着更多的Maker返佣机会
2. **波动率适中**: ETH波动比BTC大，更容易产生方向性信号
3. **资金效率**: 较低单价适合小资金测试

## 关键问题

**问题**: ETH测试中交易次数为0

**原因**:
- `min_spread=2` 设置过高
- ETH点差通常只有1 tick ($0.01)
- 策略阈值过于保守

**解决方案**:

### 方案1: 降低点差阈值
```python
# 在 run_live_paper_trading.py 中
spread_capture = SpreadCapture(
    min_spread_ticks=1,  # 从2改为1
    tick_size=0.01,
    maker_rebate=0.0002
)
```

### 方案2: 降低Alpha V2阈值
```python
# 在 mvp_trader_v2.py 中
base_alpha_threshold = 0.0005  # 从0.001降低
```

### 方案3: 使用市价单增加成交率
```python
# 提高aggressiveness阈值
if aggressiveness < 0.3:  # 从0.5降低
    decision = "LIMIT"
else:
    decision = "MARKET"
```

## 推荐ETH配置

```python
# ETH优化配置
ETH_CONFIG = {
    'symbol': 'ETHUSDT',
    'tick_size': 0.01,
    'min_spread_ticks': 1,        # 降低点差要求
    'max_position': 0.05,          # 5%仓位（ETH波动大）
    'base_alpha_threshold': 0.0005, # 降低信号阈值
    'aggressiveness_threshold': 0.3, # 更容易触发市价单
    'shadow_mode': True            # 先影子模式测试
}
```

## 运行命令

```bash
# ETH影子模式测试（推荐先运行）
cd D:/binance/new/brain_py
python run_alpha_v2_paper_trading.py --minutes 10 --symbol ETHUSDT

# ETH主动交易模式
python run_alpha_v2_paper_trading.py --minutes 10 --symbol ETHUSDT --active
```

## 监控指标

ETH交易中重点关注：

| 指标 | 目标值 | 说明 |
|------|--------|------|
| IC 1s | > 0.05 | 方向预测能力 |
| Trade Frequency | > 20% | 交易频率 |
| Spread Capture | > 0.03 bps | 点差捕获 |
| Adverse Selection | < 0.1 | 逆向选择损失 |

## 下一步行动

1. **立即**: 使用上述配置运行ETH测试
2. **观察**: IC指标是否收敛
3. **调整**: 根据IC调整阈值
4. **放量**: IC > 0.05后增加仓位
