"""
Rust Execution Engine - Python Interface
Rust执行引擎的Python接口封装

提供高性能的交易执行能力，支持微秒级延迟
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger('RustExecution')

# 尝试导入Rust模块
try:
    # 如果编译后的模块存在
    sys.path.insert(0, str(Path(__file__).parent.parent / 'rust_execution'))
    import binance_execution
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    logger.error("Rust execution engine not available. Real trading requires Rust engine.")


@dataclass
class RustExecutionConfig:
    """Rust执行引擎配置"""
    worker_threads: int = 4
    queue_size: int = 10000
    slippage_model: str = "fixed"  # fixed, proportional
    commission_rate: float = 0.001
    latency_simulation_us: int = 100


class RustExecutionEngineWrapper:
    """
    Rust执行引擎包装器 - 仅支持实盘交易
    """

    def __init__(self, config: Optional[RustExecutionConfig] = None):
        self.config = config or RustExecutionConfig()
        self.engine = None

        if not RUST_AVAILABLE:
            raise ImportError(
                "Rust execution engine is required for real trading. "
                "Please compile the Rust extension first."
            )

        self._init_rust_engine()

    def _init_rust_engine(self):
        """初始化Rust引擎"""
        cfg_dict = {
            'worker_threads': self.config.worker_threads,
            'queue_size': self.config.queue_size,
            'slippage_model': self.config.slippage_model,
        }
        self.engine = binance_execution.RustExecutionEngine(cfg_dict)
        logger.info("Rust execution engine initialized")

    def submit_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """提交订单"""
        rust_order = binance_execution.PyOrder(
            symbol=order['symbol'],
            side=order['side'],
            order_type=order['order_type'],
            quantity=order['quantity'],
            price=order.get('price')
        )
        result = self.engine.submit_order(rust_order)
        return {
            'success': result.success,
            'order_id': result.order_id,
            'executed_price': result.executed_price,
            'executed_quantity': result.executed_quantity,
            'commission': result.commission,
            'latency_us': result.latency_us,
            'error': result.error_message
        }

    def submit_orders_batch(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """批量提交订单"""
        rust_orders = [
            binance_execution.PyOrder(
                symbol=o['symbol'],
                side=o['side'],
                order_type=o['order_type'],
                quantity=o['quantity'],
                price=o.get('price')
            )
            for o in orders
        ]
        results = self.engine.submit_orders_batch(rust_orders)
        return [
            {
                'success': r.success,
                'order_id': r.order_id,
                'executed_price': r.executed_price,
                'executed_quantity': r.executed_quantity,
                'commission': r.commission,
                'latency_us': r.latency_us,
                'error': r.error_message
            }
            for r in results
        ]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.engine.get_stats()

    def reset_stats(self):
        """重置统计"""
        self.engine.reset_stats()

    def simulate_market_data(self, symbol: str, base_price: float):
        """模拟市场数据（仅用于测试）"""
        self.engine.simulate_market_data(symbol, base_price)

    def is_rust_available(self) -> bool:
        """检查Rust引擎是否可用"""
        return RUST_AVAILABLE


# 便捷函数
def create_rust_engine(config: Optional[RustExecutionConfig] = None) -> RustExecutionEngineWrapper:
    """创建Rust执行引擎"""
    return RustExecutionEngineWrapper(config)


def compile_rust_extension():
    """
    编译Rust扩展

    需要在安装Rust的环境中运行：
    ```bash
    cd rust_execution
    cargo build --release
    ```
    """
    import subprocess
    import shutil

    rust_dir = Path(__file__).parent.parent / 'rust_execution'

    if not shutil.which('cargo'):
        logger.error("Rust/Cargo not found. Please install Rust.")
        return False

    try:
        logger.info("Compiling Rust extension...")
        result = subprocess.run(
            ['cargo', 'build', '--release'],
            cwd=rust_dir,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            logger.info("Rust extension compiled successfully")
            return True
        else:
            logger.error(f"Compilation failed: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to compile Rust extension: {e}")
        return False


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 创建引擎
    engine = create_rust_engine()

    print(f"Rust available: {engine.is_rust_available()}")

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
    print(f"Order result: {result}")

    # 查看统计
    stats = engine.get_stats()
    print(f"Engine stats: {stats}")
