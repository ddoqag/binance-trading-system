#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingOrchestrator - 交易协调器

协调所有交易模块的核心组件，管理完整的交易生命周期：
- 获取 AI 交易信号
- 执行风险检查
- 计算仓位大小和杠杆
- 通过 Rust 或 Python 执行器下单
- 管理交易循环生命周期

Execution Flow:
    1. Get AI signal (direction, confidence)
    2. Risk check (can_trade?)
    3. Calculate dynamic leverage and position size
    4. Check if position exists
    5. If signal == NEUTRAL: close existing position
    6. If signal == LONG/SHORT and no position: open new position
    7. If signal != current position direction: close and reverse
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any, Tuple, Callable

# 导入订单类型
from trading.order import Order, OrderSide, OrderType, OrderStatus

# 尝试导入 Rust 执行器
try:
    from trading.rust_executor import (
        RustTradingExecutor,
        create_rust_executor,
        RUST_AVAILABLE
    )
except ImportError:
    RUST_AVAILABLE = False
    create_rust_executor = None
    RustTradingExecutor = None

# 尝试导入其他 margin_trading 模块
try:
    from .account_manager import MarginAccountManager
except ImportError:
    MarginAccountManager = None

try:
    from .position_manager import LeveragePositionManager
except ImportError:
    LeveragePositionManager = None

try:
    from .risk_controller import StandardRiskController
except ImportError:
    StandardRiskController = None

try:
    from .ai_signal import AIHybridSignalGenerator
except ImportError:
    AIHybridSignalGenerator = None

# 尝试导入 AI 上下文获取器
try:
    from trading_system.ai_context import AIContextFetcher
except ImportError:
    AIContextFetcher = None


logger = logging.getLogger(__name__)


class SignalType(Enum):
    """AI 信号类型"""
    LONG = "LONG"       # 做多信号
    SHORT = "SHORT"     # 做空信号
    NEUTRAL = "NEUTRAL" # 中性/观望信号


@dataclass
class TradingConfig:
    """交易配置数据类

    Attributes:
        symbol: 交易对，如 'BTCUSDT'
        interval: K线周期，如 '1h', '15m'
        initial_balance: 初始资金
        base_leverage: 基础杠杆倍数
        max_leverage: 最大杠杆倍数
        fee_rate: 手续费率
        slippage_rate: 滑点率
        use_rust_executor: 是否使用 Rust 执行器
        min_confidence: 最小信号置信度阈值
        cycle_interval: 交易周期间隔（秒）
    """
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    initial_balance: float = 10000.0
    base_leverage: float = 3.0
    max_leverage: float = 5.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    use_rust_executor: bool = True
    min_confidence: float = 0.5
    cycle_interval: float = 60.0  # 默认60秒一个周期


@dataclass
class TradingCycleResult:
    """交易周期执行结果"""
    success: bool
    timestamp: datetime
    signal: Optional[SignalType] = None
    action: str = "NO_ACTION"
    position_id: Optional[str] = None
    order_ids: List[str] = field(default_factory=list)
    reason: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradingOrchestrator:
    """交易协调器 - 管理完整交易流程

    该类是所有交易模块的集成中心，负责：
    1. 初始化和管理所有组件（账户、仓位、风控、AI信号、执行器）
    2. 执行交易周期（获取信号 -> 风险检查 -> 计算仓位 -> 执行交易）
    3. 管理交易循环生命周期（启动/停止）
    4. 处理错误和优雅降级

    Example:
        config = TradingConfig(symbol='BTCUSDT', use_rust_executor=True)
        orchestrator = TradingOrchestrator(config)
        orchestrator.start()  # 启动交易循环
        # ... 运行中 ...
        orchestrator.stop()   # 停止交易循环
    """

    def __init__(self, config: TradingConfig):
        """初始化交易协调器

        Args:
            config: 交易配置对象
        """
        self.config = config
        self.is_running = False
        self._stop_event = False
        self._trading_thread = None

        # 初始化日志
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.info(f"Initializing TradingOrchestrator for {config.symbol}")

        # 初始化组件
        self._init_components()

    def _init_components(self) -> None:
        """初始化所有交易组件"""
        # 1. 账户管理器
        if MarginAccountManager is not None:
            self.account_manager = MarginAccountManager()
        else:
            self.account_manager = None
            self._logger.warning("MarginAccountManager not available")

        # 2. 仓位管理器
        if LeveragePositionManager is not None:
            self.position_manager = LeveragePositionManager(self.config.symbol)
        else:
            self.position_manager = None
            self._logger.warning("LeveragePositionManager not available")

        # 3. 风险控制器
        if StandardRiskController is not None:
            self.risk_controller = StandardRiskController()
        else:
            self.risk_controller = None
            self._logger.warning("StandardRiskController not available")

        # 4. AI 信号获取器
        if AIContextFetcher is not None:
            self.ai_fetcher = AIContextFetcher()
        elif AIHybridSignalGenerator is not None:
            self.ai_fetcher = AIHybridSignalGenerator()
        else:
            self.ai_fetcher = None
            self._logger.warning("AI signal fetcher not available")

        # 5. 执行器（Rust 优先，失败则回退到 Python）
        self._init_executors()

    def _init_executors(self) -> None:
        """初始化执行器（Rust 优先）"""
        self.rust_executor = None
        self.python_executor = None

        # 尝试创建 Rust 执行器
        if self.config.use_rust_executor and RUST_AVAILABLE and create_rust_executor is not None:
            try:
                self.rust_executor = create_rust_executor(
                    initial_capital=self.config.initial_balance,
                    commission_rate=self.config.fee_rate,
                    slippage=self.config.slippage_rate
                )
                if self.rust_executor is not None:
                    self._logger.info("Rust executor initialized successfully")
            except Exception as e:
                self._logger.warning(f"Failed to initialize Rust executor: {e}")

        # 如果没有 Rust 执行器，创建 Python 回退执行器
        if self.rust_executor is None:
            self._logger.info("Using Python fallback executor")
            # Python 执行器将在需要时动态创建
            self.python_executor = None  # 延迟初始化

    def _get_ai_signal(self) -> Tuple[SignalType, float]:
        """获取 AI 交易信号

        Returns:
            (signal_type, confidence) 元组
        """
        if self.ai_fetcher is None:
            self._logger.warning("AI fetcher not available, using NEUTRAL signal")
            return SignalType.NEUTRAL, 0.0

        try:
            context = self.ai_fetcher.get_cached_context()
            direction = context.get('direction', 'sideways')
            confidence = context.get('confidence', 0.5)

            # 映射方向到信号类型
            if direction in ('up', '上涨', '看涨', 'bullish'):
                return SignalType.LONG, confidence
            elif direction in ('down', '下跌', '看跌', 'bearish'):
                return SignalType.SHORT, confidence
            else:
                return SignalType.NEUTRAL, confidence

        except Exception as e:
            self._logger.error(f"Error getting AI signal: {e}")
            return SignalType.NEUTRAL, 0.0

    def _check_risk(self, signal: SignalType, confidence: float) -> Tuple[bool, str]:
        """执行风险检查

        Args:
            signal: 交易信号
            confidence: 信号置信度

        Returns:
            (can_trade, reason) 元组
        """
        # 检查置信度阈值
        if confidence < self.config.min_confidence:
            return False, f"Confidence {confidence} below threshold {self.config.min_confidence}"

        # 使用风险控制器检查
        if self.risk_controller is not None:
            try:
                can_trade, reason = self.risk_controller.can_trade(
                    signal=signal.value,
                    confidence=confidence
                )
                return can_trade, reason
            except Exception as e:
                self._logger.error(f"Risk check error: {e}")
                return False, f"Risk check failed: {str(e)}"

        # 如果没有风险控制器，默认允许交易
        return True, ""

    def _calculate_position_params(self, signal: SignalType,
                                   confidence: float) -> Dict[str, float]:
        """计算仓位参数（大小和杠杆）

        Args:
            signal: 交易信号
            confidence: 信号置信度

        Returns:
            包含 position_size 和 leverage 的字典
        """
        if self.risk_controller is not None:
            try:
                # 计算动态杠杆
                leverage = self.risk_controller.calculate_dynamic_leverage(
                    base_leverage=self.config.base_leverage,
                    max_leverage=self.config.max_leverage,
                    confidence=confidence
                )

                # 计算仓位大小
                position_size = self.risk_controller.calculate_position_size(
                    signal=signal.value,
                    confidence=confidence,
                    leverage=leverage
                )

                return {
                    'position_size': position_size,
                    'leverage': leverage
                }
            except Exception as e:
                self._logger.error(f"Error calculating position params: {e}")

        # 默认参数
        return {
            'position_size': 0.1,  # 默认 10% 仓位
            'leverage': self.config.base_leverage
        }

    def _get_current_position(self) -> Optional[Any]:
        """获取当前仓位

        Returns:
            当前仓位对象，如果没有则返回 None
        """
        if self.position_manager is not None:
            try:
                return self.position_manager.get_position(self.config.symbol)
            except Exception as e:
                self._logger.error(f"Error getting position: {e}")
        return None

    def _execute_order(self, side: OrderSide, quantity: float,
                       price: Optional[float] = None) -> Optional[Order]:
        """执行单个订单

        Args:
            side: 买卖方向
            quantity: 数量
            price: 限价单价格（市价单为 None）

        Returns:
            Order 对象，失败返回 None
        """
        # 优先使用 Rust 执行器
        if self.rust_executor is not None:
            try:
                order = self.rust_executor.place_order(
                    symbol=self.config.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                    price=price
                )
                self._logger.info(f"Order executed via Rust: {order.order_id}")
                return order
            except Exception as e:
                self._logger.error(f"Rust executor failed: {e}")

        # 回退到 Python 执行器
        if self.python_executor is not None:
            try:
                order = self.python_executor.place_order(
                    symbol=self.config.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                    price=price
                )
                self._logger.info(f"Order executed via Python: {order.order_id}")
                return order
            except Exception as e:
                self._logger.error(f"Python executor failed: {e}")

        self._logger.error("No executor available to place order")
        return None

    def execute_batch_orders(self, orders: List[Tuple]) -> List[Order]:
        """执行批量订单

        Args:
            orders: 订单列表，每个元素为 (symbol, side, order_type, quantity, price)

        Returns:
            Order 对象列表
        """
        # 优先使用 Rust 执行器的批量方法
        if self.rust_executor is not None:
            try:
                return self.rust_executor.place_orders_batch(orders)
            except Exception as e:
                self._logger.error(f"Rust batch execution failed: {e}")

        # 回退到逐个执行
        results = []
        for order_tuple in orders:
            symbol, side, order_type, quantity, price = order_tuple[:5]
            order = self._execute_order(side, quantity, price)
            if order is not None:
                results.append(order)

        return results

    def execute_trading_cycle(self) -> Dict[str, Any]:
        """执行一个完整的交易周期

        这是核心的交易逻辑，执行以下步骤：
        1. 获取 AI 信号
        2. 风险检查
        3. 计算仓位参数
        4. 检查现有仓位
        5. 根据信号执行相应操作

        Returns:
            包含执行结果的字典
        """
        result = {
            'success': False,
            'timestamp': datetime.now().isoformat(),
            'action': 'NO_ACTION',
            'reason': ''
        }

        try:
            # Step 1: 获取 AI 信号
            signal, confidence = self._get_ai_signal()
            result['signal'] = signal.value
            result['confidence'] = confidence

            self._logger.info(f"AI Signal: {signal.value}, Confidence: {confidence:.2f}")

            # Step 2: 风险检查
            can_trade, reason = self._check_risk(signal, confidence)
            if not can_trade:
                result['blocked_by_risk'] = True
                result['reason'] = reason
                self._logger.info(f"Trade blocked by risk control: {reason}")
                return result

            # Step 3: 计算仓位参数
            position_params = self._calculate_position_params(signal, confidence)
            leverage = position_params['leverage']
            position_size = position_params['position_size']

            self._logger.info(f"Position params: size={position_size}, leverage={leverage}")

            # Step 4: 检查现有仓位
            current_position = self._get_current_position()

            # Step 5: 根据信号执行操作
            if signal == SignalType.NEUTRAL:
                # 中性信号：平掉现有仓位
                if current_position is not None:
                    self._close_position(current_position)
                    result['success'] = True
                    result['action'] = 'CLOSE_POSITION'
                    result['position_id'] = getattr(current_position, 'position_id', None)
                else:
                    result['success'] = True
                    result['action'] = 'NO_ACTION'
                    result['reason'] = 'No position to close'

            elif signal in (SignalType.LONG, SignalType.SHORT):
                # 做多/做空信号
                if current_position is not None:
                    current_side = getattr(current_position, 'side', None)

                    # 如果方向相反，先平仓再开仓
                    if (signal == SignalType.LONG and current_side == 'SHORT') or \
                       (signal == SignalType.SHORT and current_side == 'LONG'):
                        self._close_position(current_position)
                        new_position = self._open_position(signal, position_size, leverage)
                        result['success'] = new_position is not None
                        result['action'] = f'REVERSE_TO_{signal.value}'
                        result['position_id'] = getattr(new_position, 'position_id', None)

                    # 如果方向相同，检查是否需要加仓
                    elif current_side == signal.value:
                        result['success'] = True
                        result['action'] = 'HOLD'
                        result['reason'] = f'Already in {signal.value} position'

                    else:
                        # 其他情况（如 current_side 为 None）
                        new_position = self._open_position(signal, position_size, leverage)
                        result['success'] = new_position is not None
                        result['action'] = f'OPEN_{signal.value}'
                        result['position_id'] = getattr(new_position, 'position_id', None)

                else:
                    # 没有现有仓位，直接开仓
                    new_position = self._open_position(signal, position_size, leverage)
                    result['success'] = new_position is not None
                    result['action'] = f'OPEN_{signal.value}'
                    result['position_id'] = getattr(new_position, 'position_id', None)

            # 更新风险控制器状态
            if self.risk_controller is not None and result['success']:
                self.risk_controller.update_after_trade(
                    signal=signal.value,
                    confidence=confidence,
                    result=result
                )

            return result

        except Exception as e:
            self._logger.error(f"Trading cycle error: {e}")
            result['error'] = str(e)
            result['reason'] = f'Exception: {str(e)}'
            return result

    def _open_position(self, signal: SignalType, size: float,
                       leverage: float) -> Optional[Any]:
        """开新仓位

        Args:
            signal: 交易信号（LONG 或 SHORT）
            size: 仓位大小
            leverage: 杠杆倍数

        Returns:
            新仓位对象，失败返回 None
        """
        if self.position_manager is None:
            self._logger.error("Position manager not available")
            return None

        try:
            side = signal.value  # 'LONG' or 'SHORT'

            # 执行订单
            order_side = OrderSide.BUY if signal == SignalType.LONG else OrderSide.SELL
            order = self._execute_order(order_side, size)

            if order is None or order.status != OrderStatus.FILLED:
                self._logger.error("Order execution failed")
                return None

            # 创建仓位
            position = self.position_manager.open_position(
                symbol=self.config.symbol,
                side=side,
                quantity=size,
                entry_price=order.avg_price,
                leverage=leverage
            )

            self._logger.info(f"Position opened: {side} {size} @ {order.avg_price}")
            return position

        except Exception as e:
            self._logger.error(f"Error opening position: {e}")
            return None

    def _close_position(self, position: Any) -> bool:
        """平仓

        Args:
            position: 仓位对象

        Returns:
            是否成功
        """
        if self.position_manager is None:
            self._logger.error("Position manager not available")
            return False

        try:
            position_id = getattr(position, 'position_id', None)
            if position_id is None:
                self._logger.error("Position has no ID")
                return False

            # 确定平仓方向（与开仓相反）
            side = getattr(position, 'side', None)
            if side == 'LONG':
                close_side = OrderSide.SELL
            elif side == 'SHORT':
                close_side = OrderSide.BUY
            else:
                self._logger.error(f"Unknown position side: {side}")
                return False

            # 执行平仓订单
            quantity = getattr(position, 'quantity', 0)
            order = self._execute_order(close_side, quantity)

            if order is None:
                self._logger.error("Close order execution failed")
                return False

            # 关闭仓位
            success = self.position_manager.close_position(position_id)

            if success:
                self._logger.info(f"Position closed: {position_id}")
            else:
                self._logger.error(f"Failed to close position: {position_id}")

            return success

        except Exception as e:
            self._logger.error(f"Error closing position: {e}")
            return False

    def start(self) -> None:
        """启动交易循环

        启动后台交易循环，定期执行交易周期。
        """
        if self.is_running:
            raise RuntimeError("Trading loop is already running")

        self._logger.info("Starting trading loop")
        self.is_running = True
        self._stop_event = False

        # 启动交易循环（在单独线程中）
        import threading
        self._trading_thread = threading.Thread(target=self._trading_loop)
        self._trading_thread.daemon = True
        self._trading_thread.start()

    def stop(self) -> None:
        """停止交易循环

        优雅地停止交易循环。
        """
        if not self.is_running:
            return

        self._logger.info("Stopping trading loop")
        self._stop_event = True
        self.is_running = False

        # 等待线程结束
        if self._trading_thread is not None:
            self._trading_thread.join(timeout=5.0)
            self._trading_thread = None

    def _trading_loop(self) -> None:
        """后台交易循环"""
        self._logger.info("Trading loop started")

        while not self._stop_event:
            try:
                # 执行交易周期
                result = self.execute_trading_cycle()
                self._logger.debug(f"Trading cycle result: {result}")

            except Exception as e:
                self._logger.error(f"Trading cycle exception: {e}")

            # 等待下一个周期
            time.sleep(self.config.cycle_interval)

        self._logger.info("Trading loop stopped")

    def get_status(self) -> Dict[str, Any]:
        """获取协调器状态

        Returns:
            状态字典
        """
        return {
            'is_running': self.is_running,
            'symbol': self.config.symbol,
            'use_rust_executor': self.rust_executor is not None,
            'components': {
                'account_manager': self.account_manager is not None,
                'position_manager': self.position_manager is not None,
                'risk_controller': self.risk_controller is not None,
                'ai_fetcher': self.ai_fetcher is not None,
            }
        }


# 便捷函数
def create_orchestrator(symbol: str = "BTCUSDT",
                       use_rust: bool = True,
                       **kwargs) -> TradingOrchestrator:
    """创建交易协调器的工厂函数

    Args:
        symbol: 交易对
        use_rust: 是否使用 Rust 执行器
        **kwargs: 其他配置参数

    Returns:
        TradingOrchestrator 实例
    """
    config = TradingConfig(
        symbol=symbol,
        use_rust_executor=use_rust,
        **kwargs
    )
    return TradingOrchestrator(config)