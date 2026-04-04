"""
execution_core - Phase C 实盘闭环核心模块

包含：
- BinanceUserDataClient: 用户数据流 WebSocket 客户端
- OrderStateMachine: 订单状态机 (Source of Truth)
- PositionManager: 持仓与 PnL 管理
- QueueTracker: 队列位置实时跟踪
- CancelManager: 撤单决策器
- RepriceEngine: 重挂定价引擎
- LifecycleManager: 订单生命周期调度中枢
"""

from execution_core.binance_user_data_client import BinanceUserDataClient
from execution_core.order_state_machine import OrderStateMachine
from execution_core.position_manager import PositionManager
from execution_core.queue_tracker import QueueTracker
from execution_core.cancel_manager import CancelManager, CancelReason, CancelDecision
from execution_core.reprice_engine import RepriceEngine
from execution_core.lifecycle_manager import LifecycleManager

__all__ = [
    "BinanceUserDataClient",
    "OrderStateMachine",
    "PositionManager",
    "QueueTracker",
    "CancelManager",
    "CancelReason",
    "CancelDecision",
    "RepriceEngine",
    "LifecycleManager",
]
