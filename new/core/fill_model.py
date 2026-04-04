class FillModel:
    """
    基于队列位置和市场流速估算成交概率。
    """

    def __init__(self):
        self.recent_trade_volume = 0.0  # 最近 1s 成交量
        self.recent_cancel_volume = 0.0

    def update_market_flow(self, trade_vol: float, cancel_vol: float):
        self.recent_trade_volume = trade_vol
        self.recent_cancel_volume = cancel_vol

    def fill_probability(self, queue_position: float, time_horizon_s: float = 1.0) -> float:
        """
        简化版 Hazard Rate 模型：
        P(fill) = 1 - exp(-lambda * t)
        lambda = effective_flow / (queue_position + epsilon)
        """
        effective_flow = self.recent_trade_volume + self.recent_cancel_volume * 0.3
        if effective_flow <= 0:
            return 0.0

        import math
        hazard_rate = effective_flow / (queue_position + 1e-6)
        prob = 1.0 - math.exp(-hazard_rate * time_horizon_s)
        return min(1.0, max(0.0, prob))
