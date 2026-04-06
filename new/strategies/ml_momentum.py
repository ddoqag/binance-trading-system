"""
机器学习动量策略 (ML Momentum Strategy)
基于随机森林的动量预测策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List
from collections import deque

try:
    from .base import StrategyBase, Signal, SignalType
except ImportError:
    from strategies.base import StrategyBase, Signal, SignalType


class MLMomentumStrategy(StrategyBase):
    """
    机器学习动量策略

    核心逻辑：
    1. 使用随机森林分类器预测短期价格方向
    2. 自动学习市场模式，自适应调整
    3. 提供与传统策略低相关的信号

    特征工程：
    - 价格动量特征（多周期收益率）
    - 波动率特征（ATR, 实现波动率）
    - 技术指标特征（RSI, MACD, 布林带位置）
    - 成交量特征（量比, OBV）
    - 统计特征（偏度, 峰度）

    适用市场：所有市场状态（自适应）
    与其他策略相关性：低（提供另类alpha）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        config = config or {}

        # 模型参数
        self.lookback = config.get('lookback', 50)
        self.min_samples = config.get('min_samples', 100)
        self.max_samples = config.get('max_samples', 500)
        self.retrain_interval = config.get('retrain_interval', 50)

        # 模型状态
        self._model = None
        self._scaler = None
        self._is_trained = False
        self._samples_since_train = 0
        self._feature_names = []

        # 数据缓冲区
        self._feature_buffer: deque = deque(maxlen=self.max_samples)
        self._label_buffer: deque = deque(maxlen=self.max_samples)

        # 性能跟踪
        self._prediction_history: List[Dict] = []
        self._accuracy = 0.5

        # 延迟导入sklearn（可选依赖）
        self._sklearn_available = False
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.preprocessing import StandardScaler
            self._sklearn_available = True
            self._model_class = RandomForestClassifier
            self._scaler_class = StandardScaler
        except ImportError:
            print("[MLMomentumStrategy] Warning: sklearn not available, using fallback mode")

    def _generate_features(self, data: pd.DataFrame) -> np.ndarray:
        """生成机器学习特征"""
        if len(data) < self.lookback:
            return np.zeros(15)  # 返回零特征

        close = data['close']
        # 检查是否有 high/low 数据，如果没有则使用 close 的近似值
        if 'high' in data.columns and 'low' in data.columns:
            high = data['high']
            low = data['low']
        else:
            # 使用 close 价格作为 high/low 的近似
            high = close
            low = close
        volume = data.get('volume', pd.Series([1] * len(data)))

        # 1. 价格动量特征
        returns = close.pct_change().dropna()
        features = [
            returns.iloc[-5:].mean() if len(returns) >= 5 else 0,  # 5期平均收益
            returns.iloc[-10:].mean() if len(returns) >= 10 else 0,  # 10期平均收益
            returns.iloc[-20:].mean() if len(returns) >= 20 else 0,  # 20期平均收益
            (close.iloc[-1] / close.iloc[-5] - 1) if len(close) >= 5 else 0,  # 5期收益
            (close.iloc[-1] / close.iloc[-20] - 1) if len(close) >= 20 else 0,  # 20期收益
        ]

        # 2. 波动率特征
        volatility_5 = returns.iloc[-5:].std() if len(returns) >= 5 else 0
        volatility_20 = returns.iloc[-20:].std() if len(returns) >= 20 else 0

        # ATR计算
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=14).mean().iloc[-1] if len(data) >= 14 else 0

        features.extend([
            volatility_5,
            volatility_20,
            atr / close.iloc[-1] if close.iloc[-1] > 0 else 0,  # 归一化ATR
        ])

        # 3. 技术指标特征
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss if loss.iloc[-1] != 0 else 0
        rsi = 100 - (100 / (1 + rs.iloc[-1])) if hasattr(rs, 'iloc') else 50

        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12.iloc[-1] - ema26.iloc[-1] if len(close) >= 26 else 0

        # 布林带位置
        bb_middle = close.rolling(window=20).mean().iloc[-1] if len(close) >= 20 else close.iloc[-1]
        bb_std = close.rolling(window=20).std().iloc[-1] if len(close) >= 20 else 0
        bb_position = (close.iloc[-1] - bb_middle) / (2 * bb_std) if bb_std > 0 else 0

        features.extend([
            rsi / 100,  # 归一化到0-1
            macd / close.iloc[-1] if close.iloc[-1] > 0 else 0,
            bb_position,
        ])

        # 4. 成交量特征
        if 'volume' in data.columns and len(volume) >= 20:
            vol_ma = volume.rolling(window=20).mean().iloc[-1]
            vol_ratio = volume.iloc[-1] / vol_ma if vol_ma > 0 else 1

            # OBV (On Balance Volume)
            obv = (np.sign(close.diff()) * volume).cumsum().iloc[-1]
            obv_ma = (np.sign(close.diff()) * volume).cumsum().rolling(window=20).mean().iloc[-1] if len(close) >= 20 else obv
            obv_ratio = obv / obv_ma if obv_ma != 0 else 1

            features.extend([
                vol_ratio - 1,  # 量比偏差
                obv_ratio - 1,  # OBV趋势
            ])
        else:
            features.extend([0, 0])

        # 5. 统计特征
        if len(returns) >= 20:
            features.extend([
                returns.iloc[-20:].skew() if len(returns) >= 20 else 0,
                returns.iloc[-20:].kurtosis() if len(returns) >= 20 else 0,
            ])
        else:
            features.extend([0, 0])

        return np.array(features)

    def _train_model(self):
        """训练模型"""
        if not self._sklearn_available or len(self._feature_buffer) < self.min_samples:
            return False

        try:
            X = np.array(list(self._feature_buffer))
            y = np.array(list(self._label_buffer))

            # 标准化
            self._scaler = self._scaler_class()
            X_scaled = self._scaler.fit_transform(X)

            # 训练随机森林
            self._model = self._model_class(
                n_estimators=50,
                max_depth=5,
                min_samples_split=10,
                random_state=42,
                n_jobs=-1
            )
            self._model.fit(X_scaled, y)
            self._is_trained = True
            self._samples_since_train = 0

            # 计算训练集准确率
            train_pred = self._model.predict(X_scaled)
            self._accuracy = np.mean(train_pred == y)

            return True
        except Exception as e:
            print(f"[MLMomentumStrategy] Training failed: {e}")
            return False

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        生成交易信号

        Returns:
            Signal: 交易信号对象
        """
        if len(data) < self.lookback:
            return Signal(
                type=SignalType.HOLD,
                confidence=0.0,
                metadata={'error': 'Insufficient data'}
            )

        # 生成特征
        features = self._generate_features(data)

        # 计算标签（用于训练）
        current_price = data['close'].iloc[-1]
        future_return = 0
        if len(data) >= self.lookback + 5:
            future_price = data['close'].iloc[4]  # 5期后的价格
            future_return = (future_price - current_price) / current_price

        label = 1 if future_return > 0.001 else (-1 if future_return < -0.001 else 0)

        # 添加到缓冲区
        self._feature_buffer.append(features)
        self._label_buffer.append(label)
        self._samples_since_train += 1

        # 训练或重训练
        if not self._is_trained and len(self._feature_buffer) >= self.min_samples:
            self._train_model()
        elif self._is_trained and self._samples_since_train >= self.retrain_interval:
            self._train_model()

        # 生成预测
        direction = 0
        strength = 0.0
        confidence = 0.0
        prediction_prob = 0.5

        if self._is_trained and self._sklearn_available:
            try:
                features_scaled = self._scaler.transform(features.reshape(1, -1))
                prediction = self._model.predict(features_scaled)[0]
                probabilities = self._model.predict_proba(features_scaled)[0]

                # 找到预测类别的概率
                prob_idx = list(self._model.classes_).index(prediction)
                prediction_prob = probabilities[prob_idx]

                direction = prediction
                strength = min(1.0, prediction_prob)
                confidence = self._accuracy * prediction_prob

            except Exception as e:
                print(f"[MLMomentumStrategy] Prediction failed: {e}")
                direction = 0

        # 如果未训练，使用简单的动量规则作为fallback
        if not self._is_trained:
            returns = data['close'].pct_change().dropna()
            if len(returns) >= 5:
                momentum = returns.iloc[-5:].mean()
                direction = 1 if momentum > 0.001 else (-1 if momentum < -0.001 else 0)
                strength = min(1.0, abs(momentum) * 100)
                confidence = 0.3  # 低置信度

        # 根据 direction 确定 SignalType
        if direction == 1:
            signal_type = SignalType.BUY
        elif direction == -1:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.HOLD

        # 记录预测历史（用于后续评估）
        self._prediction_history.append({
            'timestamp': pd.Timestamp.now(),
            'features': features.tolist(),
            'prediction': direction,
            'price': current_price
        })

        return Signal(
            type=signal_type,
            confidence=float(confidence),
            metadata={
                'direction': direction,
                'strength': float(strength),
                'is_trained': self._is_trained,
                'accuracy': float(self._accuracy),
                'buffer_size': len(self._feature_buffer),
                'prediction_probability': float(prediction_prob),
                'samples_since_train': self._samples_since_train
            }
        )

    def get_state(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'is_trained': self._is_trained,
            'accuracy': self._accuracy,
            'buffer_size': len(self._feature_buffer),
            'sklearn_available': self._sklearn_available
        }

    def reset(self):
        super().reset()
        self._model = None
        self._scaler = None
        self._is_trained = False
        self._samples_since_train = 0
        self._feature_buffer.clear()
        self._label_buffer.clear()
        self._prediction_history.clear()
        self._accuracy = 0.5
