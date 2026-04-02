"""
P10 Hedge Fund OS - Prometheus Exporter

实时暴露策略权重、风险指标、系统模式等关键数据
用于 Grafana 监控和 AlertManager 告警

Endpoints:
- http://localhost:8000/metrics  (Python P10 决策层)
- http://localhost:9090/metrics  (Go Engine 执行层)
"""

import threading
import time
from typing import Dict, Optional, Any
from dataclasses import dataclass

# 尝试导入 prometheus_client，如果失败则提供 mock 实现
try:
    from prometheus_client import (
        start_http_server, Gauge, Counter, Histogram, Info,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("[P10Exporter] Warning: prometheus_client not installed, using mock mode")

from .hf_types import SystemMode, RiskLevel, MarketRegime


@dataclass
class P10MetricsSnapshot:
    """P10 系统状态快照"""
    timestamp: float
    system_mode: SystemMode
    risk_appetite: RiskLevel
    market_regime: str
    daily_drawdown: float
    leverage: float
    strategy_weights: Dict[str, float]
    target_exposure: float
    max_drawdown_limit: float
    
    # 扩展指标
    meta_brain_latency_ms: float = 0.0
    allocator_latency_ms: float = 0.0
    risk_check_latency_ms: float = 0.0
    
    # 策略性能
    strategy_sharpe: Dict[str, float] = None
    strategy_volatility: Dict[str, float] = None
    
    def __post_init__(self):
        if self.strategy_sharpe is None:
            self.strategy_sharpe = {}
        if self.strategy_volatility is None:
            self.strategy_volatility = {}


class P10Exporter:
    """
    P10 监控指标导出器
    
    暴露以下指标：
    - hfos_system_mode: 当前系统模式 (0=INIT, 1=GROWTH, 2=SURVIVAL, 3=CRISIS, 4=SHUTDOWN)
    - hfos_risk_appetite: 风险偏好 (0=EXTREME_CONSERVATIVE, 1=CONSERVATIVE, 2=MODERATE, 3=AGGRESSIVE)
    - hfos_market_regime: 市场状态 (0=LOW_VOL, 1=TRENDING, 2=HIGH_VOL, 3=RANGE_BOUND)
    - hfos_daily_drawdown: 日回撤百分比
    - hfos_leverage: 当前杠杆倍数
    - hfos_strategy_weight: 各策略权重
    - hfos_target_exposure: 目标敞口
    - hfos_max_drawdown_limit: 最大回撤限制
    - hfos_latency_ms: 各组件延迟
    """
    
    _instance: Optional['P10Exporter'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, port: int = 8000, enabled: bool = True):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        self.port = port
        self.enabled = enabled and PROMETHEUS_AVAILABLE
        self._running = False
        self._server_thread: Optional[threading.Thread] = None
        
        # 当前状态缓存
        self._current_snapshot: Optional[P10MetricsSnapshot] = None
        self._snapshot_lock = threading.RLock()
        
        if not self.enabled:
            print(f"[P10Exporter] Metrics export disabled (prometheus_client={PROMETHEUS_AVAILABLE})")
            return
        
        # 创建指标
        self._create_metrics()
    
    def _create_metrics(self):
        """创建 Prometheus 指标"""
        # 系统状态指标
        self.system_mode = Gauge(
            'hfos_system_mode',
            'Current system mode (0=INIT, 1=GROWTH, 2=SURVIVAL, 3=CRISIS, 4=SHUTDOWN, 5=RECOVERY)'
        )
        
        self.risk_appetite = Gauge(
            'hfos_risk_appetite',
            'Risk appetite level (0=EXTREME_CONSERVATIVE, 1=CONSERVATIVE, 2=MODERATE, 3=AGGRESSIVE)'
        )
        
        self.market_regime = Gauge(
            'hfos_market_regime',
            'Market regime (0=LOW_VOL, 1=TRENDING, 2=HIGH_VOL, 3=RANGE_BOUND, 4=UNKNOWN)'
        )
        
        # 风险指标
        self.daily_drawdown = Gauge(
            'hfos_daily_drawdown',
            'Daily drawdown percentage (negative = loss)',
            unit='ratio'
        )
        
        self.max_drawdown_limit = Gauge(
            'hfos_max_drawdown_limit',
            'Maximum allowed drawdown for current mode',
            unit='ratio'
        )
        
        self.leverage = Gauge(
            'hfos_leverage',
            'Current target leverage ratio'
        )
        
        self.target_exposure = Gauge(
            'hfos_target_exposure',
            'Target capital exposure percentage',
            unit='ratio'
        )
        
        # 策略指标
        self.strategy_weight = Gauge(
            'hfos_strategy_weight',
            'Strategy allocation weight',
            ['strategy']
        )
        
        self.strategy_sharpe = Gauge(
            'hfos_strategy_sharpe',
            'Strategy Sharpe ratio',
            ['strategy']
        )
        
        self.strategy_volatility = Gauge(
            'hfos_strategy_volatility',
            'Strategy volatility',
            ['strategy'],
            unit='ratio'
        )
        
        # 性能指标
        self.meta_brain_latency = Gauge(
            'hfos_meta_brain_latency_ms',
            'Meta Brain decision latency in milliseconds',
            unit='milliseconds'
        )
        
        self.allocator_latency = Gauge(
            'hfos_allocator_latency_ms',
            'Capital Allocator latency in milliseconds',
            unit='milliseconds'
        )
        
        self.risk_check_latency = Gauge(
            'hfos_risk_check_latency_ms',
            'Risk Kernel check latency in milliseconds',
            unit='milliseconds'
        )
        
        # 决策计数器
        self.decisions_total = Counter(
            'hfos_decisions_total',
            'Total number of decisions made',
            ['mode']
        )
        
        self.rebalances_total = Counter(
            'hfos_rebalances_total',
            'Total number of portfolio rebalances',
            ['trigger']  # 'scheduled', 'threshold', 'force'
        )
        
        # 版本信息
        self.version_info = Info(
            'hfos',
            'Hedge Fund OS version information'
        )
        self.version_info.info({'version': '1.0.0', 'phase': 'P10'})
    
    def start(self) -> bool:
        """启动 HTTP 指标服务器"""
        if self._running:
            print(f"[P10Exporter] Already running on port {self.port}")
            return True
        
        if not self.enabled:
            # Mock mode - still track metrics in memory
            self._running = True
            print("[P10Exporter] Running in MOCK mode (metrics tracked in memory)")
            print("[P10Exporter] Install prometheus-client for HTTP endpoint: pip install prometheus-client")
            return True
        
        try:
            start_http_server(self.port)
            self._running = True
            print(f"[P10Exporter] Metrics server started on http://localhost:{self.port}/metrics")
            print(f"[P10Exporter] Key metrics: hfos_system_mode, hfos_strategy_weight, hfos_daily_drawdown")
            return True
        except Exception as e:
            print(f"[P10Exporter] Failed to start: {e}")
            self.enabled = False
            return False
    
    def update_from_decision(self, decision: Any, 
                            strategy_weights: Dict[str, float],
                            drawdown: float = 0.0,
                            latency_ms: float = 0.0):
        """
        从 Capital Allocator 的决策更新指标
        
        Args:
            decision: MetaDecision 对象
            strategy_weights: 策略权重字典
            drawdown: 当前回撤
            latency_ms: 决策延迟
        """
        if not self.enabled:
            return
        
        # 更新系统模式
        mode_map = {
            SystemMode.INITIALIZING: 0,
            SystemMode.GROWTH: 1,
            SystemMode.SURVIVAL: 2,
            SystemMode.CRISIS: 3,
            SystemMode.SHUTDOWN: 4,
            SystemMode.RECOVERY: 5,
        }
        self.system_mode.set(mode_map.get(decision.mode, 0))
        
        # 更新风险偏好
        appetite_map = {
            RiskLevel.CONSERVATIVE: 0,
            RiskLevel.MODERATE: 1,
            RiskLevel.AGGRESSIVE: 2,
            RiskLevel.EXTREME: 3,
        }
        self.risk_appetite.set(appetite_map.get(decision.risk_appetite, 2))
        
        # 更新市场状态
        regime_map = {
            MarketRegime.LOW_VOLATILITY: 0,
            MarketRegime.TRENDING: 1,
            MarketRegime.HIGH_VOLATILITY: 2,
            MarketRegime.RANGE_BOUND: 3,
            MarketRegime.UNKNOWN: 4,
        }
        self.market_regime.set(regime_map.get(decision.regime, 4))
        
        # 更新风险指标
        self.daily_drawdown.set(drawdown)
        self.leverage.set(decision.leverage)
        self.target_exposure.set(decision.target_exposure)
        
        # 更新策略权重
        for strategy, weight in strategy_weights.items():
            self.strategy_weight.labels(strategy=strategy).set(weight)
        
        # 更新延迟
        self.allocator_latency.set(latency_ms)
        
        # 增加决策计数
        self.decisions_total.labels(mode=decision.mode.name).inc()
        
        # 保存快照
        with self._snapshot_lock:
            self._current_snapshot = P10MetricsSnapshot(
                timestamp=time.time(),
                system_mode=decision.mode,
                risk_appetite=decision.risk_appetite,
                market_regime=decision.regime,
                daily_drawdown=drawdown,
                leverage=decision.leverage,
                strategy_weights=strategy_weights,
                target_exposure=decision.target_exposure,
                max_drawdown_limit=0.0,  # 从 config 获取
                allocator_latency_ms=latency_ms
            )
    
    def update_from_risk_kernel(self, drawdown: float, 
                                 max_drawdown_limit: float,
                                 check_latency_ms: float = 0.0):
        """从 Risk Kernel 更新风险指标"""
        if not self.enabled:
            return
        
        self.daily_drawdown.set(drawdown)
        self.max_drawdown_limit.set(max_drawdown_limit)
        self.risk_check_latency.set(check_latency_ms)
    
    def update_strategy_performance(self, strategy: str, 
                                    sharpe: float = 0.0,
                                    volatility: float = 0.0):
        """更新策略性能指标"""
        if not self.enabled:
            return
        
        self.strategy_sharpe.labels(strategy=strategy).set(sharpe)
        self.strategy_volatility.labels(strategy=strategy).set(volatility)
    
    def record_rebalance(self, trigger: str = 'scheduled'):
        """记录再平衡事件"""
        if not self.enabled:
            return
        
        self.rebalances_total.labels(trigger=trigger).inc()
    
    def update_meta_brain_latency(self, latency_ms: float):
        """更新 Meta Brain 延迟"""
        if not self.enabled:
            return
        
        self.meta_brain_latency.set(latency_ms)
    
    def get_snapshot(self) -> Optional[P10MetricsSnapshot]:
        """获取当前状态快照"""
        with self._snapshot_lock:
            return self._current_snapshot
    
    def is_healthy(self) -> bool:
        """检查 exporter 健康状态"""
        return self._running if self.enabled else True
    
    def stop(self):
        """停止 exporter"""
        self._running = False
        print("[P10Exporter] Stopped")


# 全局实例
_exporter: Optional[P10Exporter] = None


def get_exporter(port: int = 8000, enabled: bool = True) -> P10Exporter:
    """获取全局 P10Exporter 实例"""
    global _exporter
    if _exporter is None:
        _exporter = P10Exporter(port=port, enabled=enabled)
    return _exporter


def init_metrics(port: int = 8000, enabled: bool = True) -> P10Exporter:
    """
    初始化并启动 metrics exporter
    
    Usage:
        from hedge_fund_os.exporter import init_metrics
        exporter = init_metrics(port=8000)
        
        # 在决策循环中
        exporter.update_from_decision(decision, weights, drawdown)
    """
    exporter = get_exporter(port=port, enabled=enabled)
    exporter.start()
    return exporter


# 便捷的装饰器函数
def timed_metric(metric_name: str):
    """测量函数执行时间并记录到对应指标"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            elapsed_ms = (time.time() - start) * 1000
            
            exporter = get_exporter()
            if exporter.enabled:
                if metric_name == 'meta_brain':
                    exporter.update_meta_brain_latency(elapsed_ms)
                elif metric_name == 'allocator':
                    exporter.allocator_latency.set(elapsed_ms)
                elif metric_name == 'risk_check':
                    exporter.risk_check_latency.set(elapsed_ms)
            
            return result
        return wrapper
    return decorator
