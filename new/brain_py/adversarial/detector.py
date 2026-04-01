"""
Layer B: 数据驱动陷阱检测器
- 支持 SGDClassifier (轻量在线) / XGBoost (更准确)
- 支持 ONNX 导出和推理 (低延迟)
- 输出 P_trap = P(当前是陷阱 | 特征)
"""

import numpy as np
import logging
from typing import Optional, Tuple, Any
from sklearn.linear_model import SGDClassifier
from sklearn.base import ClassifierMixin

from .types import TrapFeatures

logger = logging.getLogger(__name__)


class TrapDetector:
    """
    陷阱检测器：基于 12维特征预测当前是否是陷阱。

    Usage:
        detector = TrapDetector(model_type="sgd")
        detector.fit(X_train, y_train)
        p_trap = detector.predict_proba(features)
    """

    def __init__(
        self,
        model_type: str = "sgd",
        random_state: int = 42,
        onnx_path: Optional[str] = None,
        anomaly_detection: bool = True,
        mahalanobis_threshold: float = 5.0,
        max_anomaly_adjust: float = 0.2,
    ):
        """
        Args:
            model_type: "sgd" | "xgboost"
            random_state: 随机种子
            onnx_path: 如果提供，加载预训练 ONNX 模型
            anomaly_detection: 是否启用新型陷阱异常检测（马氏距离）
            mahalanobis_threshold: 马氏距离阈值
            max_anomaly_adjust: 最大 P_trap 调整幅度
        """
        self.model_type = model_type
        self.random_state = random_state
        self._model: Optional[ClassifierMixin] = None
        self._onnx_session = None
        self._is_fitted = False

        # 新型陷阱检测 - 马氏距离
        self.anomaly_detection = anomaly_detection
        self.mahalanobis_threshold = mahalanobis_threshold
        self.max_anomaly_adjust = max_anomaly_adjust
        self._feature_mean: Optional[np.ndarray] = None
        self._feature_cov_inv: Optional[np.ndarray] = None

        if onnx_path is not None:
            self._load_onnx(onnx_path)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: Optional[np.ndarray] = None
    ) -> None:
        """训练模型"""
        if self.model_type == "sgd":
            self._model = SGDClassifier(
                loss="log_loss",
                random_state=self.random_state,
                warm_start=True
            )
            self._model.fit(X, y, sample_weight=sample_weight)
        elif self.model_type == "xgboost":
            try:
                from xgboost import XGBClassifier
                self._model = XGBClassifier(
                    n_estimators=100,
                    learning_rate=0.1,
                    random_state=self.random_state,
                    use_label_encoder=False,
                    eval_metric="logloss"
                )
                self._model.fit(X, y, sample_weight=sample_weight)
            except ImportError:
                logger.warning("XGBoost not installed, falling back to SGD")
                self.model_type = "sgd"
                self.fit(X, y, sample_weight)
                return
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")

        self._is_fitted = True

    def partial_fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        classes: Optional[np.ndarray] = None,
        sample_weight: Optional[np.ndarray] = None
    ) -> None:
        """增量学习（用于在线更新）"""
        if not self._is_fitted:
            if self.model_type == "sgd":
                self._model = SGDClassifier(
                    loss="log_loss",
                    random_state=self.random_state,
                    warm_start=True
                )
                self._model.partial_fit(X, y, classes=classes, sample_weight=sample_weight)
                self._is_fitted = True
            else:
                # XGBoost 不支持增量，需要整个重训
                self.fit(X, y, sample_weight)
        else:
            if hasattr(self._model, "partial_fit"):
                self._model.partial_fit(X, y, sample_weight=sample_weight)
            elif self.model_type == "xgboost":
                # XGBoost 不支持增量，这里由 OnlineLearner 处理
                logger.warning("XGBoost does not support partial_fit, use fit instead")
            else:
                raise RuntimeError("Model does not support partial_fit")

    def predict_proba(self, features: TrapFeatures) -> float:
        """
        预测当前是陷阱的概率。

        Args:
            features: 12维陷阱特征

        Returns:
            p_trap: P(陷阱 | 特征) ∈ [0, 1]
        """
        if self._onnx_session is not None:
            p_trap = self._predict_onnx(features)
        else:
            X = features.to_numpy().reshape(1, -1)

            if self._model is None:
                logger.warning("Model not fitted, returning 0.0")
                return 0.0

            # 分类器 predict_proba 返回 [P(0), P(1)]
            p_trap = self._model.predict_proba(X)[0, 1]
            p_trap = float(p_trap)

        # 新型陷阱检测 - 马氏距离调整先验
        if self.anomaly_detection and self._feature_mean is not None and self._feature_cov_inv is not None:
            from .utils import calculate_mahalanobis_distance, adjust_prior_by_anomaly
            dist = calculate_mahalanobis_distance(
                features.to_numpy(), self._feature_mean, self._feature_cov_inv
            )
            p_trap = adjust_prior_by_anomaly(
                p_trap, dist,
                threshold=self.mahalanobis_threshold,
                max_adjust=self.max_anomaly_adjust
            )

        return p_trap

    def _predict_onnx(self, features: TrapFeatures) -> float:
        """ONNX 推理"""
        import onnxruntime as ort

        X = features.to_numpy().reshape(1, -1).astype(np.float32)
        input_name = self._onnx_session.get_inputs()[0].name
        output_name = self._onnx_session.get_outputs()[0].name
        proba = self._onnx_session.run([output_name], {input_name: X})[0]
        # 假设输出是 [P(0), P(1)] 或者直接是 P(1)
        if len(proba.shape) == 2 and proba.shape[1] == 2:
            return float(proba[0, 1])
        else:
            return float(proba[0])

    def _load_onnx(self, onnx_path: str) -> None:
        """加载 ONNX 模型"""
        import onnxruntime as ort
        self._onnx_session = ort.InferenceSession(onnx_path)
        logger.info(f"Loaded ONNX model from {onnx_path}")
        self._is_fitted = True

    def export_onnx(self, output_path: str) -> None:
        """导出模型到 ONNX"""
        if self.model_type == "sgd":
            from skl2onnx import convert_sklearn
            from skl2onnx.common.data_types import FloatTensorType

            initial_type = [("input", FloatTensorType([None, 12]))]
            onx = convert_sklearn(self._model, initial_types=initial_type)

            with open(output_path, "wb") as f:
                f.write(onx.SerializeToString())

            logger.info(f"Exported SGD model to ONNX: {output_path}")
        elif self.model_type == "xgboost":
            # XGBoost 导出需要额外处理，这里简化
            logger.warning("XGBoost ONNX export not implemented in MVP")
            raise NotImplementedError("XGBoost ONNX export not implemented in MVP")
        else:
            raise ValueError(f"Unsupported model_type: {self.model_type}")

    def get_accuracy(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算准确率"""
        if self._model is None:
            return 0.0
        y_pred = self._model.predict(X)
        accuracy = np.mean(y_pred == y)
        return float(accuracy)

    def get_weights(self) -> Any:
        """获取模型权重（用于版本快照）"""
        if self.model_type == "sgd":
            return {
                "coef_": self._model.coef_.copy(),
                "intercept_": self._model.intercept_.copy(),
                "classes_": self._model.classes_.copy(),
            }
        elif hasattr(self._model, "get_booster"):
            # XGBoost
            return self._model.get_booster().save_raw()
        else:
            return self._model

    def update_feature_statistics(self, X: np.ndarray) -> None:
        """
        更新特征统计量（均值和协方差）用于异常检测。

        Args:
            X: 历史特征样本 (N, 12)
        """
        if not self.anomaly_detection:
            return

        # 计算均值
        self._feature_mean = np.mean(X, axis=0)

        # 计算协方差和逆协方差
        cov = np.cov(X.T)
        # 添加小的正则化防止奇异
        reg_cov = cov + 1e-6 * np.eye(cov.shape[0])
        self._feature_cov_inv = np.linalg.inv(reg_cov)

        logger.info(f"[TrapDetector] Updated feature statistics for anomaly detection from {len(X)} samples")

    def set_weights(self, weights: Any) -> None:
        """设置模型权重（用于回滚）"""
        if self.model_type == "sgd":
            if self._model is None:
                self._model = SGDClassifier(loss="log_loss", random_state=self.random_state)
            self._model.coef_ = weights["coef_"]
            self._model.intercept_ = weights["intercept_"]
            self._model.classes_ = weights["classes_"]
            self._is_fitted = True
        elif self.model_type == "xgboost":
            from xgboost import XGBClassifier
            if self._model is None:
                self._model = XGBClassifier()
            self._model.load_model_from_raw(weights)
            self._is_fitted = True
        else:
            raise ValueError("set_weights not implemented for this model type")

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted
