"""
信号适配器 - 将字典格式的信号转换为 Signal 对象
"""

from typing import Dict, Any
from strategies.base import Signal, SignalType


def dict_to_signal(signal_dict: Dict[str, Any]) -> Signal:
    """
    将字典信号转换为 Signal 对象

    Args:
        signal_dict: 包含 direction/strength/confidence/metadata 的字典

    Returns:
        Signal 对象
    """
    direction = signal_dict.get('direction', 0)
    confidence = signal_dict.get('confidence', 0.5)
    metadata = signal_dict.get('metadata', {})

    # 转换 direction 到 SignalType
    if direction > 0.5:
        signal_type = SignalType.BUY
    elif direction < -0.5:
        signal_type = SignalType.SELL
    else:
        signal_type = SignalType.HOLD

    # 将原始信号信息保存到 metadata
    metadata['original_direction'] = direction
    metadata['strength'] = signal_dict.get('strength', 0.5)

    return Signal(
        type=signal_type,
        confidence=confidence,
        metadata=metadata
    )
