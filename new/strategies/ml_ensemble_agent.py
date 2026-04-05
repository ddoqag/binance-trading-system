"""
ML Ensemble策略 Agent
集成多个机器学习模型的集成策略
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque
import warnings

import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import BaseAgent, AgentMetadata, StrategyPriority


@dataclass
class MLModelConfig:
    """ML模型配置"""
    name: str
    weight: float = 1.0
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MLEnsembleConfig:
    """ML集成策略配置"""
    # 模型配置
    use_rf: bool = True           # 随机森林
    use_lr: bool = True           # 逻辑回归
    use_lstm: bool = False        # LSTM (可选，需要torch)

    # 特征配置
    feature_window: int = 20      # 特征窗口大小
    prediction_horizon: int = 5   # 预测未来N个周期

    # 在线学习配置
    online_learning: bool = True  # 启用在线学习
    learning_rate: float = 0.01   # 学习率
    min_samples: int = 100        # 最小训练样本数

    # 投票配置
    voting_method: str = 'weighted'  # 'uniform', 'weighted', 'confidence'
    confidence_threshold: float = 0.6  # 最小置信度阈值

    # 模型权重 (动态调整)
    model_weights: Dict[str, float] = field(default_factory=lambda: {
        'rf': 0.4,
        'lr': 0.3,
        'lstm': 0.3
    })


class MLEnsembleAgent(BaseAgent):
    """
    ML集成策略

    核心逻辑：
    - 集成多个ML模型（随机森林、逻辑回归、可选LSTM）
    - 多模型预测结果加权投票
    - 在线学习支持，根据实际结果动态调整模型权重
    - 特征工程：技术指标 + 价格序列特征

    适用市场：各种市场环境，依赖历史数据训练
    """

    METADATA = AgentMetadata(
        name="ml_ensemble",
        version="1.0.0",
        description="ML集成策略 - 多模型加权投票",
        author="System",
        priority=StrategyPriority.HIGH,
        tags=["machine_learning", "ensemble", "adaptive"],
        config={
            "use_rf": True,
            "use_lr": True,
            "use_lstm": False,
            "feature_window": 20,
            "prediction_horizon": 5,
            "online_learning": True,
            "learning_rate": 0.01,
            "voting_method": "weighted",
            "confidence_threshold": 0.6
        }
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.ml_config = MLEnsembleConfig(**self.config)
        self.signal_history: List[Dict] = []
        self.prediction_history: deque = deque(maxlen=1000)

        # 模型实例
        self.models: Dict[str, Any] = {}
        self.model_performance: Dict[str, deque] = {
            'rf': deque(maxlen=100),
            'lr': deque(maxlen=100),
            'lstm': deque(maxlen=100)
        }

        # 特征缩放参数
        self.feature_mean: Optional[np.ndarray] = None
        self.feature_std: Optional[np.ndarray] = None

        # 训练数据缓存
        self.training_features: List[np.ndarray] = []
        self.training_labels: List[int] = []

    def initialize(self) -> bool:
        """初始化策略"""
        try:
            # 初始化模型
            if self.ml_config.use_rf:
                self._init_random_forest()

            if self.ml_config.use_lr:
                self._init_logistic_regression()

            if self.ml_config.use_lstm:
                self._init_lstm()

            if not self.models:
                raise ValueError("At least one model must be enabled")

            self._initialized = True
            print(f"[MLEnsembleAgent] Initialized with {len(self.models)} models")
            return True

        except Exception as e:
            print(f"[MLEnsembleAgent] Initialization failed: {e}")
            return False

    def _init_random_forest(self):
        """初始化随机森林模型"""
        try:
            from sklearn.ensemble import RandomForestClassifier
            self.models['rf'] = RandomForestClassifier(
                n_estimators=50,
                max_depth=5,
                min_samples_split=10,
                random_state=42,
                n_jobs=-1
            )
            print("[MLEnsembleAgent] Random Forest initialized")
        except ImportError:
            print("[MLEnsembleAgent] sklearn not available, skipping RF")
            self.ml_config.use_rf = False

    def _init_logistic_regression(self):
        """初始化逻辑回归模型"""
        try:
            from sklearn.linear_model import LogisticRegression
            self.models['lr'] = LogisticRegression(
                max_iter=1000,
                random_state=42,
                solver='lbfgs'
            )
            print("[MLEnsembleAgent] Logistic Regression initialized")
        except ImportError:
            print("[MLEnsembleAgent] sklearn not available, skipping LR")
            self.ml_config.use_lr = False

    def _init_lstm(self):
        """初始化LSTM模型"""
        try:
            import torch
            import torch.nn as nn

            class SimpleLSTM(nn.Module):
                def __init__(self, input_size=10, hidden_size=32, num_layers=2):
                    super().__init__()
                    self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                                       batch_first=True, dropout=0.2)
                    self.fc = nn.Linear(hidden_size, 3)  # 3 classes: -1, 0, 1

                def forward(self, x):
                    lstm_out, _ = self.lstm(x)
                    return self.fc(lstm_out[:, -1, :])

            self.models['lstm'] = SimpleLSTM()
            self.lstm_optimizer = None
            self.lstm_criterion = None
            print("[MLEnsembleAgent] LSTM initialized")
        except ImportError:
            print("[MLEnsembleAgent] torch not available, skipping LSTM")
            self.ml_config.use_lstm = False

    def predict(self, state: Any) -> Dict[str, Any]:
        """
        执行预测

        Returns:
            {
                'direction': 1 (BUY), -1 (SELL), 0 (HOLD)
                'confidence': 置信度 0.0-1.0
                'metadata': {
                    'model_predictions': 各模型预测,
                    'ensemble_weight': 集成权重,
                    'feature_vector': 特征向量,
                    'signal_type': 信号类型
                }
            }
        """
        if not self._initialized:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Not initialized'}}

        # 解析输入数据
        prices = self._parse_state(state)
        if not prices or len(prices) < self.ml_config.feature_window + 10:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Insufficient data'}}

        # 提取特征
        features = self._extract_features(prices)
        if features is None:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'Feature extraction failed'}}

        # 获取各模型预测
        predictions = {}
        confidences = {}

        if 'rf' in self.models and self.ml_config.use_rf:
            pred, conf = self._predict_rf(features)
            predictions['rf'] = pred
            confidences['rf'] = conf

        if 'lr' in self.models and self.ml_config.use_lr:
            pred, conf = self._predict_lr(features)
            predictions['lr'] = pred
            confidences['lr'] = conf

        if 'lstm' in self.models and self.ml_config.use_lstm:
            pred, conf = self._predict_lstm(features)
            predictions['lstm'] = pred
            confidences['lstm'] = conf

        if not predictions:
            return {'direction': 0, 'confidence': 0.0, 'metadata': {'error': 'No models available'}}

        # 集成投票
        direction, confidence, voting_details = self._ensemble_vote(predictions, confidences)

        # 确定信号类型
        signal_type = 'HOLD'
        if direction == 1:
            signal_type = 'BUY_ML_ENSEMBLE' if confidence > self.ml_config.confidence_threshold else 'BUY_WEAK_ML'
        elif direction == -1:
            signal_type = 'SELL_ML_ENSEMBLE' if confidence > self.ml_config.confidence_threshold else 'SELL_WEAK_ML'

        # 构建结果
        result = {
            'direction': direction,
            'confidence': confidence,
            'metadata': {
                'model_predictions': predictions,
                'model_confidences': confidences,
                'ensemble_weights': self._get_current_weights(),
                'voting_details': voting_details,
                'feature_vector': features.tolist() if isinstance(features, np.ndarray) else features,
                'signal_type': signal_type,
                'num_models': len(predictions)
            }
        }

        # 缓存预测用于在线学习
        self.prediction_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'features': features,
            'predictions': predictions,
            'ensemble_direction': direction,
            'ensemble_confidence': confidence
        })

        # 记录信号历史
        self.signal_history.append({
            'timestamp': pd.Timestamp.now().isoformat(),
            'direction': direction,
            'confidence': confidence,
            'predictions': predictions
        })

        # 限制历史长度
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]

        return result

    def _extract_features(self, prices: List[float]) -> Optional[np.ndarray]:
        """提取特征向量"""
        try:
            window = self.ml_config.feature_window
            if len(prices) < window + 5:
                return None

            # 使用最近window个价格
            recent_prices = np.array(prices[-window:])

            features = []

            # 1. 价格统计特征
            features.append(np.mean(recent_prices))
            features.append(np.std(recent_prices))
            features.append(np.max(recent_prices))
            features.append(np.min(recent_prices))

            # 2. 收益率特征
            returns = np.diff(recent_prices) / recent_prices[:-1]
            features.append(np.mean(returns))
            features.append(np.std(returns))
            features.append(np.sum(returns > 0) / len(returns) if len(returns) > 0 else 0.5)

            # 3. 技术指标特征
            # RSI-like feature
            gains = np.where(returns > 0, returns, 0)
            losses = np.where(returns < 0, -returns, 0)
            avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else np.mean(gains)
            avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else np.mean(losses)
            rs = avg_gain / (avg_loss + 1e-10)
            rsi_like = 100 - (100 / (1 + rs))
            features.append(rsi_like / 100.0)  # Normalize to [0, 1]

            # 趋势特征 (价格相对于移动平均的位置)
            ma_short = np.mean(recent_prices[-5:])
            ma_long = np.mean(recent_prices)
            trend = (ma_short - ma_long) / ma_long if ma_long > 0 else 0
            features.append(trend)

            # 动量特征
            momentum = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] if recent_prices[0] > 0 else 0
            features.append(momentum)

            # 4. 价格位置特征
            price_range = np.max(recent_prices) - np.min(recent_prices)
            if price_range > 0:
                price_position = (recent_prices[-1] - np.min(recent_prices)) / price_range
            else:
                price_position = 0.5
            features.append(price_position)

            # 5. 波动率特征
            volatility = np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0
            features.append(volatility)

            return np.array(features)

        except Exception as e:
            print(f"[MLEnsembleAgent] Feature extraction error: {e}")
            return None

    def _predict_rf(self, features: np.ndarray) -> Tuple[int, float]:
        """随机森林预测"""
        try:
            model = self.models['rf']

            # 检查模型是否已训练
            if not hasattr(model, 'classes_'):
                # 使用启发式预测
                return self._heuristic_predict(features)

            X = features.reshape(1, -1)
            proba = model.predict_proba(X)[0]

            # 获取预测类别和置信度
            pred_class = np.argmax(proba)
            confidence = np.max(proba)

            # 映射到方向: 0->-1 (sell), 1->0 (hold), 2->1 (buy)
            direction_map = {-1: 0, 0: 1, 1: 2}
            reverse_map = {0: -1, 1: 0, 2: 1}

            direction = reverse_map.get(pred_class, 0)
            return direction, confidence

        except Exception as e:
            return self._heuristic_predict(features)

    def _predict_lr(self, features: np.ndarray) -> Tuple[int, float]:
        """逻辑回归预测"""
        try:
            model = self.models['lr']

            if not hasattr(model, 'classes_'):
                return self._heuristic_predict(features)

            X = features.reshape(1, -1)
            proba = model.predict_proba(X)[0]

            pred_class = np.argmax(proba)
            confidence = np.max(proba)

            reverse_map = {0: -1, 1: 0, 2: 1}
            direction = reverse_map.get(pred_class, 0)
            return direction, confidence

        except Exception as e:
            return self._heuristic_predict(features)

    def _predict_lstm(self, features: np.ndarray) -> Tuple[int, float]:
        """LSTM预测"""
        try:
            import torch

            model = self.models['lstm']
            # 转换为序列格式 (batch, seq_len, features)
            # 这里我们复制特征来模拟序列
            seq_len = 10
            X = torch.FloatTensor(features).unsqueeze(0).unsqueeze(0)
            X = X.repeat(1, seq_len, 1)[:, :, :10]  # 限制特征维度

            with torch.no_grad():
                output = model(X)
                proba = torch.softmax(output, dim=1)[0].numpy()

            pred_class = np.argmax(proba)
            confidence = np.max(proba)

            reverse_map = {0: -1, 1: 0, 2: 1}
            direction = reverse_map.get(pred_class, 0)
            return direction, confidence

        except Exception as e:
            return self._heuristic_predict(features)

    def _heuristic_predict(self, features: np.ndarray) -> Tuple[int, float]:
        """启发式预测（模型未训练时使用）"""
        # 基于特征向量的简单规则
        trend = features[8] if len(features) > 8 else 0  # 动量特征
        rsi = features[6] if len(features) > 6 else 0.5  # RSI-like

        if trend > 0.02 and rsi < 0.7:
            return 1, 0.6
        elif trend < -0.02 and rsi > 0.3:
            return -1, 0.6
        else:
            return 0, 0.3

    def _ensemble_vote(self, predictions: Dict[str, int],
                      confidences: Dict[str, float]) -> Tuple[int, float, Dict]:
        """集成投票"""
        voting_method = self.ml_config.voting_method

        if voting_method == 'uniform':
            # 简单多数投票
            votes = {}
            for model_name, pred in predictions.items():
                votes[pred] = votes.get(pred, 0) + 1
            direction = max(votes, key=votes.get)
            confidence = votes[direction] / len(predictions)

        elif voting_method == 'weighted':
            # 加权投票
            weights = self._get_current_weights()
            weighted_votes = {-1: 0, 0: 0, 1: 0}

            for model_name, pred in predictions.items():
                weight = weights.get(model_name, 1.0)
                weighted_votes[pred] += weight

            direction = max(weighted_votes, key=weighted_votes.get)
            total_weight = sum(weighted_votes.values())
            confidence = weighted_votes[direction] / total_weight if total_weight > 0 else 0

        else:  # confidence
            # 基于置信度的加权
            weighted_votes = {-1: 0, 0: 0, 1: 0}
            total_confidence = 0

            for model_name, pred in predictions.items():
                conf = confidences.get(model_name, 0.5)
                weighted_votes[pred] += conf
                total_confidence += conf

            direction = max(weighted_votes, key=weighted_votes.get)
            confidence = weighted_votes[direction] / total_confidence if total_confidence > 0 else 0

        # 如果置信度低于阈值，返回HOLD
        if confidence < self.ml_config.confidence_threshold:
            direction = 0

        details = {
            'method': voting_method,
            'votes': predictions,
            'final_direction': direction,
            'final_confidence': confidence
        }

        return direction, confidence, details

    def _get_current_weights(self) -> Dict[str, float]:
        """获取当前模型权重"""
        weights = {}
        if self.ml_config.use_rf:
            weights['rf'] = self.ml_config.model_weights.get('rf', 0.4)
        if self.ml_config.use_lr:
            weights['lr'] = self.ml_config.model_weights.get('lr', 0.3)
        if self.ml_config.use_lstm:
            weights['lstm'] = self.ml_config.model_weights.get('lstm', 0.3)
        return weights

    def update_with_actual(self, actual_return: float, timestamp: Optional[str] = None):
        """
        在线学习更新

        Args:
            actual_return: 实际收益（用于评估预测准确性）
            timestamp: 预测时间戳
        """
        if not self.ml_config.online_learning:
            return

        if len(self.prediction_history) == 0:
            return

        # 获取最近的预测
        recent_pred = self.prediction_history[-1]

        # 评估各模型的表现
        for model_name, pred_direction in recent_pred['predictions'].items():
            # 简单的准确性评估：预测方向与实际收益方向是否一致
            actual_direction = 1 if actual_return > 0 else (-1 if actual_return < 0 else 0)
            correct = (pred_direction == actual_direction)

            self.model_performance[model_name].append(1.0 if correct else 0.0)

        # 动态调整权重
        self._adjust_weights()

        # 添加到训练数据
        if len(self.training_features) < self.ml_config.min_samples * 2:
            self.training_features.append(recent_pred['features'])
            self.training_labels.append(actual_direction)

        # 定期重新训练
        if len(self.training_features) >= self.ml_config.min_samples:
            self._partial_fit()

    def _adjust_weights(self):
        """根据表现动态调整模型权重"""
        total_accuracy = 0
        accuracies = {}

        for model_name, performance in self.model_performance.items():
            if len(performance) > 0:
                acc = np.mean(performance)
                accuracies[model_name] = acc
                total_accuracy += acc

        if total_accuracy > 0:
            # 根据准确率比例调整权重
            for model_name, acc in accuracies.items():
                new_weight = acc / total_accuracy
                # 平滑更新
                old_weight = self.ml_config.model_weights.get(model_name, 0.33)
                lr = self.ml_config.learning_rate
                self.ml_config.model_weights[model_name] = (1 - lr) * old_weight + lr * new_weight

    def _partial_fit(self):
        """部分拟合（在线学习）"""
        try:
            if len(self.training_features) < self.ml_config.min_samples:
                return

            X = np.array(self.training_features)
            y = np.array(self.training_labels)

            # 标准化特征
            if self.feature_mean is None:
                self.feature_mean = np.mean(X, axis=0)
                self.feature_std = np.std(X, axis=0) + 1e-8

            X_scaled = (X - self.feature_mean) / self.feature_std

            # 部分拟合模型
            if 'lr' in self.models and self.ml_config.use_lr:
                try:
                    self.models['lr'].fit(X_scaled, y)
                except Exception as e:
                    pass

            # 随机森林不支持partial_fit，定期重新训练
            if 'rf' in self.models and self.ml_config.use_lr:
                if len(self.training_features) % 50 == 0:  # 每50个样本重新训练
                    try:
                        self.models['rf'].fit(X_scaled, y)
                    except Exception as e:
                        pass

        except Exception as e:
            print(f"[MLEnsembleAgent] Partial fit error: {e}")

    def _parse_state(self, state: Any) -> Optional[List[float]]:
        """解析输入状态为价格列表"""
        try:
            if isinstance(state, np.ndarray):
                return state.tolist() if len(state.shape) == 1 else state[:, 0].tolist()

            elif isinstance(state, pd.DataFrame):
                if 'close' in state.columns:
                    return state['close'].tolist()
                elif 'price' in state.columns:
                    return state['price'].tolist()
                else:
                    return state.iloc[:, 0].tolist()

            elif isinstance(state, dict):
                if 'close' in state:
                    return state['close'] if isinstance(state['close'], list) else [state['close']]
                elif 'prices' in state:
                    return state['prices']
                elif 'data' in state:
                    return self._parse_state(state['data'])

            elif isinstance(state, list):
                return state

        except Exception as e:
            print(f"[MLEnsembleAgent] Error parsing state: {e}")

        return None

    def shutdown(self) -> None:
        """关闭策略"""
        self._initialized = False
        self.models.clear()
        self.signal_history.clear()
        self.prediction_history.clear()
        self.training_features.clear()
        self.training_labels.clear()
        print("[MLEnsembleAgent] Shutdown complete")

    def get_signal_stats(self) -> Dict[str, Any]:
        """获取信号统计"""
        if not self.signal_history:
            return {'total_signals': 0}

        buy_signals = sum(1 for s in self.signal_history if s['direction'] == 1)
        sell_signals = sum(1 for s in self.signal_history if s['direction'] == -1)
        hold_signals = sum(1 for s in self.signal_history if s['direction'] == 0)

        # 模型表现统计
        model_stats = {}
        for model_name, performance in self.model_performance.items():
            if len(performance) > 0:
                model_stats[model_name] = {
                    'accuracy': np.mean(performance),
                    'samples': len(performance)
                }

        return {
            'total_signals': len(self.signal_history),
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'hold_signals': hold_signals,
            'avg_confidence': np.mean([s['confidence'] for s in self.signal_history]),
            'model_weights': self._get_current_weights(),
            'model_performance': model_stats,
            'training_samples': len(self.training_features)
        }


# 兼容性别名
MLEnsembleStrategy = MLEnsembleAgent
