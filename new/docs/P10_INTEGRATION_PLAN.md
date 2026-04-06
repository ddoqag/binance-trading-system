# P10 Hedge Fund OS 集成计划

> 将 P10 Hedge Fund OS 与现有 self_evolving_trader.py 集成

---

## 集成目标

将 P10 的自主决策能力（Meta Brain + Capital Allocator + Risk Kernel + Evolution Engine）
与现有的 SelfEvolvingTrader 整合，实现：

1. **全自动策略选择** - Meta Brain 根据市场状态自动选择策略
2. **动态资金分配** - Capital Allocator 根据风险调整仓位
3. **三级风控** - Risk Kernel 自动切换 GROWTH/SURVIVAL/CRISIS 模式
4. **策略进化** - Evolution Engine 自动淘汰/生成策略

---

## 集成架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SelfEvolvingTrader (P1-P9)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Live Order   │  │ Live Risk    │  │ Self-Evolving│              │
│  │ Manager      │  │ Manager      │  │ Meta-Agent   │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         └─────────────────┴─────────────────┘                       │
│                           │                                         │
│  ┌────────────────────────┼────────────────────────────────┐       │
│  │           brain_py     │    Components                   │       │
│  │  ┌─────────────┐       │       ┌──────────────┐         │       │
│  │  │ Agent       │◄──────┴──────►│ Regime       │         │       │
│  │  │ Registry    │               │ Detector     │         │       │
│  │  └─────────────┘               └──────────────┘         │       │
│  │  ┌─────────────┐  ┌──────────┐  ┌──────────────┐         │       │
│  │  │ PBT Trainer │  │ MoE      │  │ World Model  │         │       │
│  │  └─────────────┘  └──────────┘  └──────────────┘         │       │
│  └──────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ 集成层
┌─────────────────────────────────────────────────────────────────────┐
│                    P10 Hedge Fund OS                                │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Orchestrator                              │   │
│  │  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐  │   │
│  │  │  Meta Brain   │→ │ Capital Allocator │→ │  Risk Kernel │  │   │
│  │  │  (决策大脑)   │   │  (资金分配器)     │   │  (风险内核)  │  │   │
│  │  └──────────────┘  └──────────────────┘  └──────────────┘  │   │
│  │                           ↓                                  │   │
│  │  ┌────────────────────────────────────────────────────────┐ │   │
│  │  │              Evolution Engine (进化引擎)                │ │   │
│  │  │  - 策略生命周期管理 (Birth→Trial→Active→Decline→Death) │ │   │
│  │  │  - 自动淘汰/生成策略                                   │ │   │
│  │  └────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 集成步骤

### Phase 1: 基础集成 (1-2天)

#### 1.1 创建 P10 包装器

```python
# p10_integration.py
from hedge_fund_os import (
    Orchestrator, OrchestratorConfig,
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig,
    RiskKernel, RiskThresholds,
    EvolutionEngine, EvolutionConfig,
)

class P10Integration:
    """P10 Hedge Fund OS 集成包装器"""

    def __init__(self, trader_config):
        self.config = self._create_p10_config(trader_config)
        self.orchestrator = None
        self.evolution_engine = None

    def _create_p10_config(self, trader_config):
        """从 trader 配置创建 P10 配置"""
        return OrchestratorConfig(
            loop_interval_ms=trader_config.check_interval_seconds * 1000,
            drawdown_survival_threshold=0.05,
            drawdown_crisis_threshold=0.10,
            drawdown_shutdown_threshold=0.15,
            emergency_stop_on_error=True,
        )

    def initialize(self, price_history, strategy_allocations):
        """初始化 P10 组件"""
        # 创建 Meta Brain
        meta_brain = MetaBrain(MetaBrainConfig())

        # 创建 Capital Allocator
        capital_allocator = CapitalAllocator(
            CapitalAllocatorConfig()
        )

        # 创建 Risk Kernel
        risk_kernel = RiskKernel(RiskThresholds())

        # 创建 Evolution Engine
        self.evolution_engine = EvolutionEngine(
            EvolutionConfig()
        )

        # 创建 Orchestrator
        self.orchestrator = Orchestrator(
            config=self.config,
            meta_brain=meta_brain,
            capital_allocator=capital_allocator,
            risk_kernel=risk_kernel,
            evolution_engine=self.evolution_engine,
            metrics_enabled=True,
        )

        # 初始化
        return self.orchestrator.initialize()

    def start(self):
        """启动 P10"""
        if self.orchestrator:
            return self.orchestrator.start()
        return False

    def stop(self):
        """停止 P10"""
        if self.orchestrator:
            self.orchestrator.stop("manual")

    def on_trading_cycle(self, market_data, current_allocations):
        """交易周期回调"""
        # 更新 Meta Brain 市场数据
        if self.orchestrator and self.orchestrator.meta_brain:
            self.orchestrator.meta_brain.update_market_data(market_data)

        # 获取 P10 决策
        decision = self._get_p10_decision()

        # 获取资金分配
        allocation = self._get_p10_allocation(decision)

        # 风险检查
        if not self._risk_check(allocation):
            return None

        return {
            'decision': decision,
            'allocation': allocation,
            'mode': self.orchestrator.state.mode if self.orchestrator else None,
        }

    def _get_p10_decision(self):
        """获取 P10 决策"""
        if self.orchestrator:
            return self.orchestrator.meta_brain.decide()
        return None

    def _get_p10_allocation(self, decision):
        """获取资金分配"""
        if self.orchestrator and decision:
            return self.orchestrator.capital_allocator.allocate(decision)
        return None

    def _risk_check(self, allocation):
        """风险检查"""
        if self.orchestrator and allocation:
            return self.orchestrator.risk_kernel.check(allocation)
        return True

    def on_strategy_performance(self, strategy_id, performance):
        """策略表现回调 - 用于 Evolution Engine"""
        if self.evolution_engine:
            self.evolution_engine.update_performance(strategy_id, performance)
```

#### 1.2 修改 SelfEvolvingTrader

```python
# self_evolving_trader.py

class SelfEvolvingTrader:
    def __init__(self, config: TraderConfig):
        # ... 现有初始化 ...

        # P10 集成
        self.p10 = None
        if config.enable_p10:
            from p10_integration import P10Integration
            self.p10 = P10Integration(config)

    async def initialize(self):
        # ... 现有初始化 ...

        # 初始化 P10
        if self.p10:
            logger.info("[SelfEvolvingTrader] Initializing P10 Hedge Fund OS...")
            self.p10.initialize(
                price_history=list(self.price_history),
                strategy_allocations=self.meta_agent.get_weights() if self.meta_agent else {}
            )
            self.p10.start()
            logger.info("[SelfEvolvingTrader] P10 started successfully")

    async def _trading_cycle(self):
        """交易周期 - 集成 P10"""

        # P10 决策
        p10_result = None
        if self.p10:
            market_data = self._build_market_data()
            current_allocations = self.meta_agent.get_weights() if self.meta_agent else {}

            p10_result = self.p10.on_trading_cycle(market_data, current_allocations)

            if p10_result:
                logger.info(f"[P10] Mode: {p10_result['mode']}, Decision: {p10_result['decision']}")

        # 使用 P10 的资金分配（如果可用）
        if p10_result and p10_result['allocation']:
            strategy_allocations = p10_result['allocation']['allocations']
        else:
            # 回退到原有逻辑
            strategy_allocations = await self._select_strategies()

        # ... 剩余交易逻辑 ...

    def _build_market_data(self):
        """构建市场数据用于 P10"""
        return {
            'price': self._get_current_price(),
            'price_history': list(self.price_history),
            'regime': self.current_regime.value if self.current_regime else 'unknown',
            'timestamp': time.time(),
        }

    async def stop(self):
        # ... 现有停止逻辑 ...

        # 停止 P10
        if self.p10:
            logger.info("[SelfEvolvingTrader] Stopping P10...")
            self.p10.stop()
```

### Phase 2: 策略进化集成 (1-2天)

#### 2.1 策略基因映射

```python
# strategy_genome_adapter.py

from hedge_fund_os import StrategyGenome, StrategyStatus
from strategies.base import StrategyBase

class StrategyGenomeAdapter:
    """将现有策略适配到 P10 StrategyGenome"""

    @staticmethod
    def to_genome(strategy: StrategyBase, strategy_name: str) -> StrategyGenome:
        """将策略转换为基因"""
        metadata = strategy.get_metadata()

        return StrategyGenome(
            id=strategy_name,
            name=metadata.name,
            version=metadata.version,
            strategy_type=metadata.tags[0] if metadata.tags else "unknown",
            parameters=metadata.params,
            status=StrategyStatus.ACTIVE,
        )

    @staticmethod
    def from_genome(genome: StrategyGenome):
        """从基因创建策略（用于进化生成的新策略）"""
        # 根据 strategy_type 创建对应策略
        strategy_map = {
            'trend_following': 'DualMAStrategy',
            'mean_reversion': 'RSIStrategy',
            'momentum': 'MomentumStrategy',
            # ... 其他策略类型
        }

        strategy_class = strategy_map.get(genome.strategy_type)
        if strategy_class:
            # 动态导入并创建
            module = __import__('strategies', fromlist=[strategy_class])
            cls = getattr(module, strategy_class)
            return cls(config=genome.parameters)

        return None
```

#### 2.2 进化回调集成

```python
# 在 SelfEvolvingTrader 中添加

def _on_strategy_performance_update(self, strategy_name: Dict):
    """策略表现更新回调"""
    if not self.p10 or not self.p10.evolution_engine:
        return

    # 获取策略表现
    performance = self._calculate_strategy_performance(strategy_name)

    # 更新 Evolution Engine
    self.p10.evolution_engine.update_performance(strategy_name, performance)

    # 检查是否需要淘汰
    genome = self.p10.evolution_engine.get_strategy_genome(strategy_name)
    if genome and genome.should_be_eliminated():
        logger.warning(f"[P10] Strategy {strategy_name} marked for elimination")
        # 降低权重或停止策略
        if self.meta_agent:
            self.meta_agent.update_weight(strategy_name, 0.0)

def _calculate_strategy_performance(self, strategy_name: str):
    """计算策略表现指标"""
    # 从 meta_agent 获取历史信号记录
    if not self.meta_agent:
        return None

    signals = self.meta_agent.get_strategy_signals(strategy_name)

    if not signals:
        return None

    # 计算指标
    total_pnl = sum(s.get('pnl', 0) for s in signals)
    win_count = sum(1 for s in signals if s.get('pnl', 0) > 0)
    loss_count = sum(1 for s in signals if s.get('pnl', 0) < 0)

    return {
        'total_return': total_pnl,
        'win_rate': win_count / len(signals) if signals else 0,
        'sharpe_ratio': self._calculate_sharpe(signals),
        'max_drawdown': self._calculate_max_drawdown(signals),
        'trade_count': len(signals),
    }
```

### Phase 3: 模式切换集成 (1天)

#### 3.1 回撤监控

```python
# 在 SelfEvolvingTrader 中添加回撤监控

def _update_drawdown(self):
    """更新回撤并通知 P10"""
    if not self.order_manager:
        return

    # 计算当前回撤
    current_equity = self.order_manager.get_account_value()
    peak_equity = getattr(self, '_peak_equity', current_equity)

    if current_equity > peak_equity:
        self._peak_equity = current_equity

    drawdown = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0

    # 通知 P10 Risk Kernel
    if self.p10 and self.p10.orchestrator:
        self.p10.orchestrator.risk_kernel.update_drawdown(drawdown)

        # 检查模式切换
        current_mode = self.p10.orchestrator.state.mode

        if drawdown >= 0.15 and current_mode != SystemMode.SHUTDOWN:
            logger.critical(f"[P10] Emergency shutdown triggered! Drawdown: {drawdown:.2%}")
            self.p10.orchestrator.emergency_shutdown("drawdown_15pct")
            asyncio.create_task(self.stop())
        elif drawdown >= 0.10 and current_mode not in [SystemMode.CRISIS, SystemMode.SHUTDOWN]:
            logger.warning(f"[P10] Entering CRISIS mode. Drawdown: {drawdown:.2%}")
            self.p10.orchestrator.force_mode_switch(SystemMode.CRISIS, "drawdown_10pct")
        elif drawdown >= 0.05 and current_mode == SystemMode.GROWTH:
            logger.warning(f"[P10] Entering SURVIVAL mode. Drawdown: {drawdown:.2%}")
            self.p10.orchestrator.force_mode_switch(SystemMode.SURVIVAL, "drawdown_5pct")
```

#### 3.2 模式响应

```python
# 根据 P10 模式调整交易行为

def _get_position_limit(self):
    """根据 P10 模式获取仓位限制"""
    if not self.p10 or not self.p10.orchestrator:
        return 1.0  # 默认 100%

    mode = self.p10.orchestrator.state.mode

    limits = {
        SystemMode.GROWTH: 1.0,      # 100%
        SystemMode.SURVIVAL: 0.5,    # 50%
        SystemMode.CRISIS: 0.2,      # 20%
        SystemMode.SHUTDOWN: 0.0,    # 0%
    }

    return limits.get(mode, 1.0)

def _can_open_new_position(self):
    """检查是否可以开新仓"""
    if not self.p10 or not self.p10.orchestrator:
        return True

    mode = self.p10.orchestrator.state.mode

    # CRISIS 和 SHUTDOWN 模式不允许开新仓
    if mode in [SystemMode.CRISIS, SystemMode.SHUTDOWN]:
        return False

    return True
```

### Phase 4: 测试与验证 (2-3天)

#### 4.1 集成测试

```python
# tests/test_p10_integration.py

import pytest
from self_evolving_trader import SelfEvolvingTrader, TraderConfig
from p10_integration import P10Integration

class TestP10Integration:
    """P10 集成测试"""

    def test_p10_initialization(self):
        """测试 P10 初始化"""
        config = TraderConfig(enable_p10=True)
        trader = SelfEvolvingTrader(config)

        assert trader.p10 is not None
        assert isinstance(trader.p10, P10Integration)

    def test_p10_trading_cycle(self):
        """测试 P10 交易周期"""
        config = TraderConfig(enable_p10=True)
        trader = SelfEvolvingTrader(config)

        # 模拟交易周期
        market_data = {'price': 50000, 'regime': 'trending'}
        result = trader.p10.on_trading_cycle(market_data, {})

        assert result is not None
        assert 'decision' in result
        assert 'allocation' in result

    def test_p10_mode_switch_on_drawdown(self):
        """测试回撤触发的模式切换"""
        config = TraderConfig(enable_p10=True)
        trader = SelfEvolvingTrader(config)
        trader.p10.initialize([], {})
        trader.p10.start()

        # 模拟 10% 回撤
        trader._peak_equity = 10000
        trader.order_manager = MockOrderManager(equity=9000)

        trader._update_drawdown()

        # 应该切换到 CRISIS 模式
        assert trader.p10.orchestrator.state.mode == SystemMode.CRISIS
```

#### 4.2 性能测试

```python
# tests/test_p10_performance.py

class TestP10Performance:
    """P10 性能测试"""

    def test_p10_latency(self):
        """测试 P10 决策延迟"""
        import time

        config = TraderConfig(enable_p10=True)
        trader = SelfEvolvingTrader(config)
        trader.p10.initialize([], {})

        # 测量 100 次决策延迟
        latencies = []
        for _ in range(100):
            start = time.time()
            trader.p10.on_trading_cycle({'price': 50000}, {})
            latencies.append((time.time() - start) * 1000)

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)

        # 断言: 平均延迟 < 100ms, 最大延迟 < 200ms
        assert avg_latency < 100, f"Average latency {avg_latency:.2f}ms exceeds 100ms"
        assert max_latency < 200, f"Max latency {max_latency:.2f}ms exceeds 200ms"
```

---

## 配置选项

```python
# config.yaml

trading:
  symbol: "BTCUSDT"
  initial_capital: 1000

# P10 配置
p10:
  enabled: true

  orchestrator:
    loop_interval_ms: 100
    drawdown_survival_threshold: 0.05
    drawdown_crisis_threshold: 0.10
    drawdown_shutdown_threshold: 0.15
    emergency_stop_on_error: true

  capital_allocator:
    method: "risk_parity"  # 或 "equal_weight", "inverse_volatility"
    rebalance_threshold: 0.1

  evolution_engine:
    enabled: true
    elimination_threshold: 0.3  # 淘汰阈值
    mutation_rate: 0.1
```

---

## 迁移检查清单

- [ ] Phase 1: 基础集成
  - [ ] 创建 `p10_integration.py`
  - [ ] 修改 `SelfEvolvingTrader.__init__`
  - [ ] 修改 `SelfEvolvingTrader.initialize`
  - [ ] 修改 `SelfEvolvingTrader._trading_cycle`
  - [ ] 修改 `SelfEvolvingTrader.stop`

- [ ] Phase 2: 策略进化
  - [ ] 创建 `strategy_genome_adapter.py`
  - [ ] 实现 `_on_strategy_performance_update`
  - [ ] 实现 `_calculate_strategy_performance`

- [ ] Phase 3: 模式切换
  - [ ] 实现 `_update_drawdown`
  - [ ] 实现 `_get_position_limit`
  - [ ] 实现 `_can_open_new_position`

- [ ] Phase 4: 测试
  - [ ] 创建 `tests/test_p10_integration.py`
  - [ ] 创建 `tests/test_p10_performance.py`
  - [ ] 运行所有测试
  - [ ] 模拟交易验证

---

## 回滚计划

如果集成出现问题，可以通过设置 `enable_p10: false` 回退到原有逻辑：

```python
# self_evolving_trader.py

if p10_result and self.config.enable_p10:
    # 使用 P10 决策
    strategy_allocations = p10_result['allocation']['allocations']
else:
    # 回退到原有逻辑
    strategy_allocations = await self._select_strategies()
```

---

## 时间表

| 阶段 | 预计时间 | 依赖 |
|------|----------|------|
| Phase 1: 基础集成 | 1-2天 | 无 |
| Phase 2: 策略进化 | 1-2天 | Phase 1 |
| Phase 3: 模式切换 | 1天 | Phase 1 |
| Phase 4: 测试验证 | 2-3天 | Phase 1-3 |
| **总计** | **5-8天** | - |

---

## 注意事项

1. **性能影响**: P10 会增加约 10-50ms 的决策延迟，需确保总延迟仍在可接受范围内
2. **资源占用**: Evolution Engine 会占用额外内存存储策略基因
3. **回滚准备**: 建议先在小资金账户测试 P10 集成
4. **监控告警**: 密切关注 P10 触发的模式切换和策略淘汰
