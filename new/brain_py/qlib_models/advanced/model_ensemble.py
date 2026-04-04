"""
model_ensemble.py - Top-K ensemble of Qlib benchmark models.

Provides:
- QlibTopKEnsemble: average/topk voting ensemble wrapping multiple QlibBaseModels.
"""

import os
import json
from typing import List, Dict, Any
import numpy as np

from ..base import QlibBaseModel, QlibModelConfig


class QlibTopKEnsemble(QlibBaseModel):
    """
    Ensemble of Qlib models.

    Modes:
      - 'mean': simple average of all model predictions
      - 'topk': average of top-k models by recent performance
    """

    def __init__(
        self,
        models: List[QlibBaseModel] = None,
        mode: str = "mean",
        topk: int = 3,
        config: QlibModelConfig = None,
    ):
        if config is None:
            config = QlibModelConfig(
                model_type="ensemble",
                input_dim=models[0].config.input_dim if models else 20,
                lookback_window=models[0].config.lookback_window if models else 20,
                mode=mode,
                topk=topk,
            )
        super().__init__(config)
        self.models = models or []
        self.mode = mode
        self.topk = topk
        self._performance_scores: Dict[int, float] = {}

    def build_model(self) -> Any:
        return None  # Ensemble does not have a single torch module

    def add_model(self, model: QlibBaseModel) -> None:
        self.models.append(model)

    def update_performance(self, model_idx: int, mse: float) -> None:
        self._performance_scores[model_idx] = mse

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not self.models:
            raise RuntimeError("No models in ensemble")

        predictions = []
        for model in self.models:
            if not model.is_fitted:
                continue
            pred = model.predict(x)
            predictions.append(pred)

        if not predictions:
            raise RuntimeError("No fitted models available")

        stacked = np.stack(predictions, axis=0)  # (num_models, batch, 1)

        if self.mode == "mean":
            return np.mean(stacked, axis=0)

        if self.mode == "topk":
            # If no perf scores, fall back to mean
            if not self._performance_scores:
                return np.mean(stacked, axis=0)
            # Lower MSE = better; pick topk
            ranked = sorted(self._performance_scores.items(), key=lambda kv: kv[1])
            selected = [idx for idx, _ in ranked[: min(self.topk, len(ranked))]]
            valid = [i for i in selected if i < stacked.shape[0]]
            if not valid:
                return np.mean(stacked, axis=0)
            return np.mean(stacked[valid], axis=0)

        return np.mean(stacked, axis=0)

    def fit(self, x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        if not self.models:
            raise RuntimeError("No models to fit")

        results = {}
        for idx, model in enumerate(self.models):
            metrics = model.fit(x, y)
            results[f"model_{idx}"] = metrics
            self.update_performance(idx, metrics.get("loss", 1e6))

        self._is_fitted = True
        return {"ensemble_loss": np.mean([m.get("loss", 0) for m in results.values()])}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        meta = {
            "config": self.config.to_dict(),
            "mode": self.mode,
            "topk": self.topk,
            "performance_scores": self._performance_scores,
            "model_paths": [],
        }
        for idx, model in enumerate(self.models):
            model_path = os.path.join(os.path.dirname(path), f"ensemble_model_{idx}.pt")
            model.save(model_path)
            meta["model_paths"].append(model_path)

        meta_path = path if path.endswith(".json") else path + ".json"
        with open(meta_path, "w") as f:
            json.dump(meta, f)

    def load(self, path: str) -> bool:
        meta_path = path if path.endswith(".json") else path + ".json"
        if not os.path.exists(meta_path):
            return False
        with open(meta_path, "r") as f:
            meta = json.load(f)
        self.config = QlibModelConfig.from_dict(meta["config"])
        self.mode = meta["mode"]
        self.topk = meta["topk"]
        self._performance_scores = meta.get("performance_scores", {})
        # Note: model instances must be reconstructed by caller if needed
        return True
