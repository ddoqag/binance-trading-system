#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略基类 - 所有交易策略的基础类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import pandas as pd
import logging


class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        """
        初始化策略

        Args:
            name: 策略名称
            params: 策略参数字典
        """
        self.name = name
        self.params = params or {}
        self.logger = logging.getLogger(f'Strategy.{name}')
        self.position = 0  # 当前持仓：1=多头, -1=空头, 0=空仓
        self.last_signal = 0

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            df: K线数据 DataFrame，需包含 open, high, low, close, volume

        Returns:
            包含信号列的 DataFrame，signal 列取值: 1=买入, -1=卖出, 0=持有
        """
        pass

    def get_params(self) -> Dict[str, Any]:
        """获取策略参数"""
        return self.params.copy()

    def set_params(self, params: Dict[str, Any]):
        """设置策略参数"""
        self.params.update(params)

    def reset(self):
        """重置策略状态"""
        self.position = 0
        self.last_signal = 0
