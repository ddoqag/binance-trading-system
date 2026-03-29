#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器学习策略 - ML-Based Trading Strategy
"""

import pandas as pd
import numpy as np
from typing import Optional, Any
from .base import BaseStrategy


class MLStrategy(BaseStrategy):
    """机器学习策略"""

    def __init__(self, model: Optional[Any] = None,
                 feature_columns: Optional[list] = None,
                 threshold: float = 0.5):
        """
        初始化机器学习策略

        Args:
            model: 训练好的 ML 模型
            feature_columns: 特征列名列表
            threshold: 预测概率阈值
        """
        super().__init__(
            name="ML_Strategy",
            params={'threshold': threshold}
        )
        self.model = model
        self.feature_columns = feature_columns or []
        self.threshold = threshold

    def set_model(self, model: Any, feature_columns: list):
        """
        设置模型

        Args:
            model: 训练好的模型
            feature_columns: 特征列名
        """
        self.model = model
        self.feature_columns = feature_columns

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        基于 ML 模型生成交易信号

        Args:
            df: 包含特征的 K线数据

        Returns:
            包含信号的 DataFrame
        """
        df = df.copy()

        if self.model is None or not self.feature_columns:
            self.logger.warning("Model or feature columns not set, returning neutral signals")
            df['signal'] = 0
            df['prediction'] = 0.5
            return df

        # 检查特征列是否存在
        missing_cols = [col for col in self.feature_columns if col not in df.columns]
        if missing_cols:
            self.logger.warning(f"Missing feature columns: {missing_cols}")
            df['signal'] = 0
            df['prediction'] = 0.5
            return df

        # 准备特征数据
        features = df[self.feature_columns].fillna(0).values

        # 预测
        try:
            if hasattr(self.model, 'predict_proba'):
                # 分类模型，获取概率
                probas = self.model.predict_proba(features)
                # 假设第二列是上涨概率
                df['prediction'] = probas[:, 1] if probas.shape[1] > 1 else probas[:, 0]
            else:
                # 回归模型或直接预测
                df['prediction'] = self.model.predict(features)
        except Exception as e:
            self.logger.error(f"Prediction error: {e}")
            df['signal'] = 0
            df['prediction'] = 0.5
            return df

        # 生成信号
        df['signal'] = 0
        # 预测上涨概率超过阈值时买入
        df.loc[df['prediction'] > self.threshold, 'signal'] = 1
        # 预测下跌概率高时卖出
        df.loc[df['prediction'] < (1 - self.threshold), 'signal'] = -1

        self.logger.debug(
            f"ML signals: {len(df)} rows, "
            f"buy: {(df['signal'] == 1).sum()}, "
            f"sell: {(df['signal'] == -1).sum()}, "
            f"mean prediction: {df['prediction'].mean():.3f}"
        )

        return df
