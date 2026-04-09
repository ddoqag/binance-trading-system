"""
FeatureEngine - 特征引擎

将原始市场数据流处理为富含时间序列信息的状态向量。
输出10维状态，包含EMA和动量特征。
"""
import numpy as np
from collections import deque
from typing import Dict, Optional


class FeatureEngine:
    """
    特征引擎：将原始数据转换为具有时间维度（EMA，动量）的状态向量。

    输出10维状态:
    [ofi, ofi_ema, ofi_mom, trade_press, trade_ema, micro_diff, spread, volatility, inventory, toxic]
    """

    def __init__(self, ema_alpha: float = 0.3, history_len: int = 10):
        """
        初始化特征引擎

        Args:
            ema_alpha: EMA平滑系数，越大对新数据越敏感
            history_len: 历史记录长度
        """
        self.ema_alpha = ema_alpha
        self.history_len = history_len

        # 历史数据队列
        self.ofi_hist = deque(maxlen=history_len)
        self.trade_hist = deque(maxlen=history_len)
        self.price_hist = deque(maxlen=history_len * 2)

        # EMA跟踪器
        self.ofi_ema = 0.0
        self.trade_ema = 0.0
        self._first_point = True

    def _update_ema(self, current_val: float, prev_ema: float) -> float:
        """计算指数移动平均"""
        if self._first_point:
            return current_val
        return self.ema_alpha * current_val + (1 - self.ema_alpha) * prev_ema

    def compute_ofi(self, bid_price: float, bid_size: float,
                    ask_price: float, ask_size: float) -> float:
        """计算一档订单流不平衡 (Order Flow Imbalance)"""
        if bid_size + ask_size == 0:
            return 0.0
        return (bid_size - ask_size) / (bid_size + ask_size)

    def compute_microprice(self, bid_price: float, bid_size: float,
                          ask_price: float, ask_size: float) -> float:
        """计算微观价格 (Micro Price)"""
        if bid_size + ask_size == 0:
            return (bid_price + ask_price) / 2.0
        # 以对方订单量为权重的加权价格
        return (bid_price * ask_size + ask_price * bid_size) / (bid_size + ask_size)

    def compute_volatility(self, window: int = 10) -> float:
        """基于历史价格计算波动率"""
        if len(self.price_hist) < window:
            return 0.01  # 默认1%

        prices = list(self.price_hist)[-window:]
        returns = np.diff(prices) / prices[:-1]
        return np.std(returns) if len(returns) > 0 else 0.01

    def compute_state(self, orderbook: Dict, inventory: float = 0.0,
                     toxic_score: float = 0.0, trade_pressure: float = 0.0) -> np.ndarray:
        """
        计算并返回当前的状态向量

        Args:
            orderbook: 订单簿数据 {'bids': [[price, qty], ...], 'asks': [...]}
            inventory: 当前持仓
            toxic_score: 毒流检测分数
            trade_pressure: 交易压力 [-1, 1]

        Returns:
            10维状态向量
        """
        # 解析订单簿
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            # 返回零状态（表示数据不可用）
            return np.zeros(10, dtype=np.float32)

        # 处理不同的数据格式（字典或列表）
        if isinstance(bids[0], dict):
            bid_price, bid_size = bids[0]['price'], bids[0]['qty']
            ask_price, ask_size = asks[0]['price'], asks[0]['qty']
        else:
            bid_price, bid_size = bids[0][0], bids[0][1]
            ask_price, ask_size = asks[0][0], asks[0][1]
        mid_price = (bid_price + ask_price) / 2.0

        # 记录价格历史
        self.price_hist.append(mid_price)

        # 1. 计算OFI
        ofi = self.compute_ofi(bid_price, bid_size, ask_price, ask_size)
        self.ofi_hist.append(ofi)

        # 2. 更新OFI EMA
        self.ofi_ema = self._update_ema(ofi, self.ofi_ema)

        # 3. 计算OFI动量
        ofi_momentum = ofi - self.ofi_ema

        # 4. 更新交易压力EMA
        self.trade_hist.append(trade_pressure)
        self.trade_ema = self._update_ema(trade_pressure, self.trade_ema)

        # 5. 计算微观价格偏移
        micro_price = self.compute_microprice(bid_price, bid_size, ask_price, ask_size)
        micro_diff = (micro_price - mid_price) / mid_price

        # 6. 计算相对点差
        spread = (ask_price - bid_price) / mid_price

        # 7. 计算波动率
        volatility = self.compute_volatility()

        if self._first_point and len(self.ofi_hist) > 0:
            self._first_point = False

        # 构建状态向量
        state = np.array([
            ofi,                    # 0: 当前订单流不平衡 [-1, 1]
            self.ofi_ema,          # 1: OFI的EMA [-1, 1]
            ofi_momentum,          # 2: OFI动量 [-2, 2]
            trade_pressure,        # 3: 当前交易压力 [-1, 1]
            self.trade_ema,        # 4: 交易压力的EMA [-1, 1]
            micro_diff,            # 5: 微观价格偏移 [-0.001, 0.001]
            spread,                # 6: 相对点差 [0, 0.01]
            volatility,            # 7: 波动率 [0, 0.1]
            inventory,             # 8: 当前持仓 [-1, 1]
            toxic_score            # 9: 毒流分数 [0, 1]
        ], dtype=np.float32)

        return state

    def get_state_names(self) -> list:
        """返回状态维度名称（用于调试和可视化）"""
        return [
            'ofi', 'ofi_ema', 'ofi_mom', 'trade_press',
            'trade_ema', 'micro_diff', 'spread',
            'volatility', 'inventory', 'toxic'
        ]

    def reset(self):
        """重置引擎状态"""
        self.ofi_hist.clear()
        self.trade_hist.clear()
        self.price_hist.clear()
        self.ofi_ema = 0.0
        self.trade_ema = 0.0
        self._first_point = True


# 测试代码
if __name__ == "__main__":
    print("="*60)
    print("FeatureEngine Test")
    print("="*60)

    engine = FeatureEngine(ema_alpha=0.3)

    # 模拟10个tick的数据
    for i in range(10):
        orderbook = {
            'bids': [[50000 + i*0.5, 2.0 + i*0.1]],
            'asks': [[50001 + i*0.5, 1.5 - i*0.05]]
        }

        state = engine.compute_state(
            orderbook=orderbook,
            inventory=0.1,
            toxic_score=0.2,
            trade_pressure=0.3
        )

        print(f"\nTick {i+1}:")
        print(f"  OFI: {state[0]:.4f}")
        print(f"  OFI EMA: {state[1]:.4f}")
        print(f"  OFI Momentum: {state[2]:.4f}")
        print(f"  Micro Diff: {state[5]:.6f}")
        print(f"  Volatility: {state[7]:.4f}")

    print("\n" + "="*60)
    print("Test completed!")
    print("="*60)
