"""
RewardEngine - 奖励引擎

基于短期市场反馈计算即时、可学习的奖励信号，引导SAC学习正确预测。
核心思想：奖励"正确的预测行为"而非延迟的、嘈杂的最终利润。
"""
import numpy as np
from collections import deque
from typing import Optional, Dict
from dataclasses import dataclass


@dataclass
class TradeOutcome:
    """交易结果记录"""
    timestamp: float
    side: str  # 'BUY' or 'SELL'
    fill_price: float
    mid_price_at_fill: float
    qty: float
    alpha_score: float  # 决策时的Alpha信号


class RewardEngine:
    """
    奖励引擎：计算即时奖励信号

    奖励组成：
    1. 方向正确性：预测方向与实际移动方向一致
    2. 微观移动捕获：信号强度与未来波动匹配
    3. 逆向选择惩罚：成交后立即不利
    4. 持仓风险惩罚：绝对持仓惩罚
    """

    def __init__(self,
                 horizon_seconds: float = 3.0,
                 w_dir: float = 0.5,
                 w_micro: float = 0.3,
                 w_adv: float = 0.4,
                 w_pos: float = 0.1,
                 clip_range: tuple = (-2.0, 2.0)):
        """
        初始化奖励引擎

        Args:
            horizon_seconds: 未来收益计算窗口（秒）
            w_dir: 方向正确性权重
            w_micro: 微观移动捕获权重
            w_adv: 逆向选择惩罚权重
            w_pos: 持仓惩罚权重
            clip_range: 奖励裁剪范围
        """
        self.horizon = horizon_seconds
        self.w_dir = w_dir
        self.w_micro = w_micro
        self.w_adv = w_adv
        self.w_pos = w_pos
        self.clip_range = clip_range

        # 历史记录
        self.trade_outcomes: deque = deque(maxlen=100)
        self.reward_history: deque = deque(maxlen=500)

        # 统计
        self.total_reward = 0.0
        self.trade_count = 0

    def compute(self,
                alpha_score: float,
                mid_price_now: float,
                mid_price_future: float,
                fill_price: Optional[float] = None,
                position: float = 0.0,
                side: Optional[str] = None) -> float:
        """
        计算单步奖励

        Args:
            alpha_score: 决策时的综合Alpha信号
            mid_price_now: 决策时的中间价
            mid_price_future: 决策后horizon秒的中间价
            fill_price: 成交价（如果未成交则为None）
            position: 当前持仓
            side: 交易方向 ('BUY'/'SELL')

        Returns:
            标量奖励值
        """
        # 1. 方向正确性奖励 [-1, 1]
        pred_direction = np.sign(alpha_score) if abs(alpha_score) > 0.001 else 0
        future_return = (mid_price_future - mid_price_now) / mid_price_now

        if pred_direction != 0:
            # 预测方向与未来实际移动方向一致则奖励
            sign_correct = 1.0 if (pred_direction * future_return) > 0 else -1.0
        else:
            sign_correct = 0.0

        # 2. 微观价格移动捕获奖励
        # 鼓励信号强度与未来波动幅度匹配
        price_move_bps = future_return * 10000  # 转换为基点
        price_move_normalized = np.clip(price_move_bps, -10, 10) / 10.0  # 归一化到[-1, 1]
        micro_move_captured = price_move_normalized * pred_direction

        # 3. 逆向选择惩罚（仅在成交时计算）
        adverse_penalty = 0.0
        if fill_price is not None and side is not None:
            if side == 'BUY':
                # 买贵了：成交价 > 未来中间价
                adverse = max(0, (fill_price - mid_price_future) / mid_price_future)
            else:  # 'SELL'
                # 卖便宜了：成交价 < 未来中间价
                adverse = max(0, (mid_price_future - fill_price) / mid_price_future)
            adverse_penalty = adverse * 10000  # 转换为基点

        # 4. 持仓风险惩罚
        position_penalty = abs(position) * 0.1  # 轻微惩罚大仓位

        # 5. 合成奖励
        reward = (
            self.w_dir * sign_correct +
            self.w_micro * micro_move_captured -
            self.w_adv * adverse_penalty -
            self.w_pos * position_penalty
        )

        # 6. 奖励裁剪
        reward = np.clip(reward, self.clip_range[0], self.clip_range[1])

        # 记录
        self.reward_history.append({
            'timestamp': np.datetime64('now'),
            'reward': reward,
            'components': {
                'sign_correct': sign_correct,
                'micro_move': micro_move_captured,
                'adverse': adverse_penalty,
                'position': position_penalty
            }
        })
        self.total_reward += reward

        return reward

    def compute_delayed_reward(self,
                               trade: TradeOutcome,
                               mid_price_future: float) -> float:
        """
        计算延迟奖励（用于实际成交后的反馈）

        Args:
            trade: 交易结果记录
            mid_price_future: 未来中间价

        Returns:
            奖励值
        """
        return self.compute(
            alpha_score=trade.alpha_score,
            mid_price_now=trade.mid_price_at_fill,
            mid_price_future=mid_price_future,
            fill_price=trade.fill_price,
            position=trade.qty if trade.side == 'BUY' else -trade.qty,
            side=trade.side
        )

    def get_statistics(self) -> Dict:
        """获取奖励统计信息"""
        if not self.reward_history:
            return {
                'mean': 0.0,
                'std': 0.0,
                'min': 0.0,
                'max': 0.0,
                'total': 0.0,
                'count': 0
            }

        rewards = [r['reward'] for r in self.reward_history]
        return {
            'mean': np.mean(rewards),
            'std': np.std(rewards),
            'min': np.min(rewards),
            'max': np.max(rewards),
            'total': self.total_reward,
            'count': len(rewards),
            'positive_ratio': sum(1 for r in rewards if r > 0) / len(rewards)
        }

    def reset(self):
        """重置引擎状态"""
        self.trade_outcomes.clear()
        self.reward_history.clear()
        self.total_reward = 0.0
        self.trade_count = 0


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("RewardEngine Test")
    print("=" * 60)

    engine = RewardEngine(horizon_seconds=3.0)

    # 测试场景1：正确预测上涨
    print("\n[场景1] 正确预测上涨")
    reward = engine.compute(
        alpha_score=0.5,  # 看涨
        mid_price_now=50000,
        mid_price_future=50100,  # 实际上涨
        fill_price=50001,
        position=0.1,
        side='BUY'
    )
    print(f"  Reward: {reward:.4f}")
    print(f"  方向正确，应获得正奖励")

    # 测试场景2：错误预测（预测涨，实际跌）
    print("\n[场景2] 错误预测（预测涨，实际跌）")
    reward = engine.compute(
        alpha_score=0.5,  # 看涨
        mid_price_now=50000,
        mid_price_future=49900,  # 实际下跌
        fill_price=50001,
        position=0.1,
        side='BUY'
    )
    print(f"  Reward: {reward:.4f}")
    print(f"  方向错误，应获得负奖励")

    # 测试场景3：逆向选择（买后立即跌）
    print("\n[场景3] 逆向选择（买后立即跌）")
    reward = engine.compute(
        alpha_score=0.3,  # 看涨
        mid_price_now=50000,
        mid_price_future=49950,  # 成交后下跌
        fill_price=50002,  # 买贵了
        position=0.1,
        side='BUY'
    )
    print(f"  Reward: {reward:.4f}")
    print(f"  逆向选择，应有惩罚")

    # 统计
    print("\n" + "=" * 60)
    print("Reward Statistics")
    print("=" * 60)
    stats = engine.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value:.4f}")

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)
