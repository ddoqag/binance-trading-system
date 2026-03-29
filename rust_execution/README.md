# Rust Execution Engine

高性能交易执行引擎，使用Rust实现，通过PyO3提供Python绑定。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Python 接口层                            │
│              (rust_execution_bridge.py)                     │
├─────────────────────────────────────────────────────────────┤
│                    Rust 绑定层                              │
│                   (PyO3 封装)                               │
├─────────────────────────────────────────────────────────────┤
│                    Rust 核心层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ 执行引擎     │  │ 订单簿管理   │  │ 撮合引擎     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| 订单提交延迟 | < 10 μs | 从调用到确认 |
| 订单簿更新 | < 5 μs | 处理一个tick |
| 批量订单 | 100k+/s | 批量处理能力 |
| 内存占用 | < 1GB | 正常运行时 |

## 文件结构

```
rust_execution/
├── Cargo.toml          # Rust 项目配置
├── src/
│   ├── lib.rs          # Python 绑定入口
│   ├── types.rs        # 类型定义
│   ├── engine.rs       # 执行引擎核心
│   └── orderbook.rs    # 订单簿实现 (可选)
└── README.md           # 本文档
```

## 编译安装

### 前提条件

- Rust 1.70+ (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
- Python 3.8+
- maturin (`pip install maturin`)

### 编译步骤

```bash
# 进入Rust项目目录
cd rust_execution

# 使用maturin构建Python扩展
maturin develop --release

# 或使用cargo直接构建（仅Rust库）
cargo build --release
```

### Python 使用

```python
from trading.rust_execution_bridge import create_rust_engine, RustExecutionConfig

# 创建引擎
config = RustExecutionConfig(
    worker_threads=4,
    queue_size=10000,
    slippage_model="proportional"
)
engine = create_rust_engine(config)

# 模拟市场数据
engine.simulate_market_data("BTCUSDT", 50000.0)

# 提交订单
order = {
    'symbol': 'BTCUSDT',
    'side': 'BUY',
    'order_type': 'MARKET',
    'quantity': 0.1,
}
result = engine.submit_order(order)

print(f"Executed at {result['executed_price']}, latency: {result['latency_us']}μs")
```

## 配置选项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| worker_threads | int | 4 | Tokio运行时线程数 |
| queue_size | int | 10000 | 订单队列大小 |
| slippage_model | str | "fixed" | 滑点模型: fixed/proportional |
| commission_rate | float | 0.001 | 手续费率 |
| latency_simulation_us | int | 100 | 模拟延迟(微秒) |

## 特性说明

### 1. 异步执行
- 基于Tokio异步运行时
- 非阻塞订单处理
- 批量订单优化

### 2. 订单簿管理
- 多级价格深度
- 快速快照功能
- 增量更新支持

### 3. 风险控制
- 订单预校验
- 价格保护
- 数量限制

### 4. 性能监控
- 微秒级延迟统计
- 吞吐量监控
- 错误追踪

## 订单类型支持

| 类型 | 支持 | 说明 |
|------|------|------|
| MARKET | ✓ | 市价单 |
| LIMIT | ✓ | 限价单 |
| IOC | ✓ | 立即成交或取消 |
| FOK | ✓ | 全部成交或取消 |
| STOP_LIMIT | 计划 | 止损限价 |
| TRAILING_STOP | 计划 | 追踪止损 |

## 与Python系统的集成

```python
# 在交易系统中的使用示例
from trading.rust_execution_bridge import RustExecutionEngineWrapper

class HighFrequencyTrader:
    def __init__(self):
        self.engine = RustExecutionEngineWrapper()

    def on_orderbook_update(self, orderbook_data):
        # 快速处理订单簿更新
        signal = self.strategy.generate_signal(orderbook_data)

        if signal:
            # 低延迟下单
            order = {
                'symbol': 'BTCUSDT',
                'side': 'BUY' if signal > 0 else 'SELL',
                'order_type': 'IOC',
                'quantity': abs(signal),
                'price': orderbook_data['ask'][0]['price']
            }
            result = self.engine.submit_order(order)

            if result['latency_us'] > 100:
                logger.warning(f"High latency: {result['latency_us']}μs")
```

## 测试

```bash
# Rust单元测试
cargo test

# Python集成测试
pytest tests/test_rust_execution.py -v
```

## 优化建议

1. **CPU亲和性**: 将工作线程绑定到特定核心
2. **内存池**: 使用对象池减少分配
3. **无锁队列**: 使用crossbeam的无锁数据结构
4. **SIMD**: 使用AVX2/NEON加速计算

## 未来扩展

- [ ] 真实Binance WebSocket连接
- [ ] FPGA硬件加速接口
- [ ] 内核旁路网络 (DPDK)
- [ ] 分布式撮合引擎

## 参考资料

- [PyO3文档](https://pyo3.rs/)
- [Tokio文档](https://tokio.rs/)
- [高频交易系统设计](https://www.amazon.com/Building-Trading-Systems-High-Performance/dp/0470563769)
