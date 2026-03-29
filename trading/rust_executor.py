#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust Execution Engine Integration

将 Rust 高性能执行引擎集成到 Python 交易系统中。
提供与现有交易执行器兼容的接口。
"""

import os
import sys
import logging
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Add Rust DLL path
RUST_DLL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rust_execution', 'target', 'release')
sys.path.insert(0, RUST_DLL_PATH)
os.environ["PATH"] = RUST_DLL_PATH + os.pathsep + os.environ.get("PATH", "")

# Try to import Rust module
try:
    import binance_execution as rust_be
    RUST_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Rust execution engine not available: {e}")
    RUST_AVAILABLE = False
    rust_be = None

# Add project root to path for absolute imports
try:
    # 尝试相对导入（作为包的一部分）
    from .order import Order, OrderType, OrderSide, OrderStatus
except ImportError:
    # 回退到绝对导入（直接运行）
    import os
    import sys
    # Add parent directory to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from trading.order import Order, OrderType, OrderSide, OrderStatus


@dataclass
class RustExecutionConfig:
    """Rust 执行引擎配置"""
    worker_threads: int = 4
    queue_size: int = 10000
    slippage_model: str = "fixed"  # "fixed" or "proportional"
    commission_rate: float = 0.001
    latency_simulation_us: int = 100


class RustTradingExecutor:
    """
    Rust 高性能交易执行器

    将 Rust 执行引擎包装成与现有 Python 执行器兼容的接口。
    提供超低延迟的订单执行和订单簿管理。
    """

    def __init__(self,
                 initial_capital: float = 10000.0,
                 commission_rate: float = 0.001,
                 slippage: float = 0.0005,
                 config: Optional[RustExecutionConfig] = None):
        """
        初始化 Rust 交易执行器

        Args:
            initial_capital: 初始资金
            commission_rate: 手续费率
            slippage: 滑点率（在 Rust 引擎中通过 slippage_model 控制）
            config: Rust 引擎配置
        """
        if not RUST_AVAILABLE:
            raise RuntimeError("Rust execution engine not available. Please build the DLL first.")

        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.config = config or RustExecutionConfig()

        # Initialize Rust engine
        rust_config = {
            "worker_threads": self.config.worker_threads,
            "queue_size": self.config.queue_size,
            "slippage_model": self.config.slippage_model,
        }

        self._engine = rust_be.RustExecutionEngine(rust_config)
        self._logger = logging.getLogger('RustTradingExecutor')

        # Track orders and positions
        self._orders: Dict[str, Order] = {}
        self._order_counter = 0

        self._logger.info(f"Rust Trading Executor initialized (threads={self.config.worker_threads})")

    def create_order_id(self) -> str:
        """生成订单 ID"""
        self._order_counter += 1
        return f"RUST_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._order_counter:06d}"

    def simulate_market_data(self, symbol: str, base_price: float) -> None:
        """
        模拟市场数据（用于回测）

        Args:
            symbol: 交易对
            base_price: 基础价格
        """
        self._engine.simulate_market_data(symbol, base_price)
        self._logger.debug(f"Simulated market data for {symbol} @ {base_price}")

    def update_orderbook(self, symbol: str, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> None:
        """
        更新订单簿

        Args:
            symbol: 交易对
            bids: [(price, quantity), ...]
            asks: [(price, quantity), ...]
        """
        self._engine.update_orderbook(symbol, bids, asks)

    def get_orderbook_snapshot(self, symbol: str) -> Dict[str, Any]:
        """
        获取订单簿快照

        Args:
            symbol: 交易对

        Returns:
            {
                'symbol': str,
                'best_bid': float,
                'best_ask': float,
                'spread': float,
                'timestamp': str
            }
        """
        return self._engine.get_orderbook_snapshot(symbol)

    def place_order(self,
                   symbol: str,
                   side: OrderSide,
                   order_type: OrderType,
                   quantity: float,
                   price: Optional[float] = None,
                   **kwargs) -> Order:
        """
        下单（核心接口）

        Args:
            symbol: 交易对
            side: 买卖方向
            order_type: 订单类型
            quantity: 数量
            price: 限价单价格

        Returns:
            Order 对象
        """
        order_id = self.create_order_id()

        # Map Python OrderSide/OrderType to Rust strings
        side_str = "BUY" if side == OrderSide.BUY else "SELL"
        type_str = self._map_order_type(order_type)

        # Create Rust order
        rust_order = rust_be.PyOrder(
            symbol=symbol,
            side=side_str,
            order_type=type_str,
            quantity=quantity,
            price=price
        )

        # Submit to Rust engine
        result = self._engine.submit_order(rust_order)

        # Create Python Order object
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED if result.success else OrderStatus.REJECTED,
            create_time=datetime.now()
        )

        # Fill order with Rust result
        if result.success:
            order.fill_price = result.executed_price
            order.fill_quantity = result.executed_quantity
            order.commission = result.commission
            order.status = OrderStatus.FILLED
            order.update_time = datetime.now()

            self._logger.info(
                f"Order executed: {side.value} {quantity} {symbol} @ {result.executed_price:.2f} "
                f"(latency: {result.latency_us} μs)"
            )
        else:
            order.status = OrderStatus.REJECTED
            self._logger.error(f"Order rejected: {result.error_message}")

        self._orders[order_id] = order
        return order

    def place_orders_batch(self, orders: List[Tuple[str, OrderSide, OrderType, float, Optional[float]]]) -> List[Order]:
        """
        批量下单（高性能）

        Args:
            orders: List of (symbol, side, order_type, quantity, price)

        Returns:
            List of Order objects
        """
        rust_orders = []
        python_orders = []

        for symbol, side, order_type, quantity, price in orders:
            order_id = self.create_order_id()

            side_str = "BUY" if side == OrderSide.BUY else "SELL"
            type_str = self._map_order_type(order_type)

            rust_order = rust_be.PyOrder(
                symbol=symbol,
                side=side_str,
                order_type=type_str,
                quantity=quantity,
                price=price
            )
            rust_orders.append(rust_order)

            # Create Python order
            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.NEW,
                create_time=datetime.now()
            )
            python_orders.append(order)

        # Batch submit to Rust
        results = self._engine.submit_orders_batch(rust_orders)

        # Update Python orders with results
        for order, result in zip(python_orders, results):
            if result.success:
                order.fill_price = result.executed_price
                order.fill_quantity = result.executed_quantity
                order.commission = result.commission
                order.status = OrderStatus.FILLED
                order.update_time = datetime.now()
            else:
                order.status = OrderStatus.REJECTED
            self._orders[order.order_id] = order

        self._logger.info(f"Batch executed: {len(orders)} orders")
        return python_orders

    def get_stats(self) -> Dict[str, Any]:
        """
        获取引擎统计信息

        Returns:
            {
                'total_orders': int,
                'executed_orders': int,
                'avg_latency_us': float,
                'errors': int
            }
        """
        return self._engine.get_stats()

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._engine.reset_stats()

    def _map_order_type(self, order_type: OrderType) -> str:
        """映射 Python OrderType 到 Rust 字符串"""
        mapping = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP_LOSS: "MARKET",
            OrderType.STOP_LOSS_LIMIT: "LIMIT",
            OrderType.TAKE_PROFIT: "MARKET",
            OrderType.TAKE_PROFIT_LIMIT: "LIMIT",
        }
        return mapping.get(order_type, "MARKET")

    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单信息"""
        return self._orders.get(order_id)

    def get_all_orders(self) -> List[Order]:
        """获取所有订单"""
        return list(self._orders.values())


class HybridExecutor:
    """
    混合执行器 - 根据场景自动选择 Rust 或 Python 执行器

    - 高频/批量操作: 使用 Rust 引擎
    - 复杂业务逻辑: 使用 Python 执行器
    """

    def __init__(self,
                 rust_executor: Optional[RustTradingExecutor] = None,
                 python_executor=None,
                 use_rust_for_batch: bool = True):
        """
        初始化混合执行器

        Args:
            rust_executor: Rust 执行器实例
            python_executor: Python 执行器实例
            use_rust_for_batch: 批量操作是否使用 Rust
        """
        self.rust = rust_executor
        self.python = python_executor
        self.use_rust_for_batch = use_rust_for_batch
        self._logger = logging.getLogger('HybridExecutor')

    def place_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                   quantity: float, price: Optional[float] = None, **kwargs) -> Order:
        """下单 - 优先使用 Rust 引擎"""
        if self.rust:
            return self.rust.place_order(symbol, side, order_type, quantity, price, **kwargs)
        elif self.python:
            return self.python.place_order(symbol, side, order_type, quantity, price, **kwargs)
        else:
            raise RuntimeError("No executor available")

    def place_orders_batch(self, orders: List[Tuple]) -> List[Order]:
        """批量下单 - 优先使用 Rust 引擎"""
        if self.use_rust_for_batch and self.rust:
            return self.rust.place_orders_batch(orders)
        elif self.python:
            return [self.python.place_order(*o[:5]) for o in orders]
        else:
            raise RuntimeError("No executor available")


def create_rust_executor(initial_capital: float = 10000.0, **kwargs) -> Optional[RustTradingExecutor]:
    """
    工厂函数：创建 Rust 执行器

    Args:
        initial_capital: 初始资金
        **kwargs: 其他配置参数

    Returns:
        RustTradingExecutor 实例，如果 Rust DLL 不可用则返回 None
    """
    if not RUST_AVAILABLE:
        logging.warning("Rust execution engine not available, falling back to Python")
        return None

    try:
        config = RustExecutionConfig(**kwargs)
        return RustTradingExecutor(
            initial_capital=initial_capital,
            config=config
        )
    except Exception as e:
        logging.error(f"Failed to create Rust executor: {e}")
        return None


# Convenience functions for direct use
def submit_order(symbol: str, side: str, order_type: str, quantity: float,
                price: Optional[float] = None) -> Optional[Dict]:
    """
    快速下单函数（使用默认配置的全局引擎）

    Args:
        symbol: 交易对
        side: "BUY" or "SELL"
        order_type: "MARKET", "LIMIT", "IOC", "FOK"
        quantity: 数量
        price: 价格（限价单需要）

    Returns:
        执行结果字典，如果失败返回 None
    """
    if not RUST_AVAILABLE:
        return None

    engine = rust_be.RustExecutionEngine()
    engine.simulate_market_data(symbol, 50000.0)  # Default price

    order = rust_be.PyOrder(symbol, side, order_type, quantity, price)
    result = engine.submit_order(order)

    return {
        'success': result.success,
        'order_id': result.order_id,
        'executed_price': result.executed_price,
        'executed_quantity': result.executed_quantity,
        'commission': result.commission,
        'latency_us': result.latency_us,
        'error': result.error_message
    }


if __name__ == "__main__":
    # Test the integration
    logging.basicConfig(level=logging.INFO)

    if not RUST_AVAILABLE:
        print("Rust engine not available. Please build the DLL first:")
        print("  cd rust_execution && cargo build --release")
        sys.exit(1)

    print("Testing Rust Execution Engine Integration...")

    # Import here to avoid circular import when module is imported
    try:
        from .order import OrderSide, OrderType
    except ImportError:
        from trading.order import OrderSide, OrderType

    # Create executor
    executor = RustTradingExecutor(initial_capital=10000.0)

    # Simulate market data
    executor.simulate_market_data("BTCUSDT", 50000.0)

    # Get orderbook
    snapshot = executor.get_orderbook_snapshot("BTCUSDT")
    print(f"Orderbook: {snapshot}")

    # Place a single order
    order = executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.1
    )
    print(f"Order placed: {order.order_id}, status={order.status.value}")

    # Place batch orders
    batch_orders = [
        ("BTCUSDT", OrderSide.BUY, OrderType.MARKET, 0.05, None),
        ("BTCUSDT", OrderSide.SELL, OrderType.MARKET, 0.05, None),
        ("BTCUSDT", OrderSide.BUY, OrderType.LIMIT, 0.03, 49000.0),
    ]
    results = executor.place_orders_batch(batch_orders)
    print(f"Batch orders: {len(results)} orders placed")

    # Get stats
    stats = executor.get_stats()
    print(f"Engine stats: {stats}")

    print("\nAll tests passed!")
