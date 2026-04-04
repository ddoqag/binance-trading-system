"""
hist_model.py - Qlib HIST benchmark port.

HIST (History Information Exploiting Stock Transformer) uses concept-oriented
shared information among stocks. This is a simplified single-asset port that
uses learnable concept embeddings to model latent sector/topic correlations.

Reference hyperparameters (Alpha360):
  d_feat=6, hidden_size=64, num_layers=2, dropout=0,
  lr=1e-4, base_model=LSTM
"""

import os
from typing import Dict, Any
import numpy as np

import torch
import torch.nn as nn

from ..base import QlibBaseModel, QlibModelConfig


class _HISTNet(nn.Module):
    def __init__(self, d_feat: int, hidden_size: int, num_layers: int, dropout: float, num_concepts: int = 8):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=d_feat,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        # Concept attention: stock representation attends to concept prototypes
        self.concept_embed = nn.Parameter(torch.randn(num_concepts, hidden_size))
        self.query_proj = nn.Linear(hidden_size, hidden_size)
        self.key_proj = nn.Linear(hidden_size, hidden_size)
        self.fc = nn.Linear(hidden_size * 2, 1)
        self.num_concepts = num_concepts

    def forward(self, x):
        # x: (batch, seq_len, d_feat)
        lstm_out, _ = self.lstm(x)
        stock_repr = lstm_out[:, -1, :]  # (batch, hidden_size)

        # Attention over concepts
        q = self.query_proj(stock_repr).unsqueeze(1)  # (batch, 1, hidden)
        k = self.key_proj(self.concept_embed).unsqueeze(0)  # (1, num_concepts, hidden)
        attn = torch.softmax(torch.matmul(q, k.transpose(-2, -1)) / np.sqrt(q.size(-1)), dim=-1)
        concept_repr = torch.matmul(attn, self.concept_embed.unsqueeze(0)).squeeze(1)  # (batch, hidden)

        combined = torch.cat([stock_repr, concept_repr], dim=-1)
        return self.fc(combined)


class HISTModel(QlibBaseModel):
    """HIST model (simplified single-asset port)."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="hist",
                input_dim=20,
                lookback_window=20,
                d_feat=20,
                hidden_size=64,
                num_layers=2,
                dropout=0.0,
                num_concepts=8,
                lr=1e-4,
                n_epochs=100,
                batch_size=256,
                device="cpu",
            )
        super().__init__(config)
        self._model = None
        self._optimizer = None
        self._criterion = nn.MSELoss()

    def build_model(self) -> Any:
        d_feat = self.config.extra.get("d_feat", self.config.input_dim)
        hidden_size = self.config.extra.get("hidden_size", 64)
        num_layers = self.config.extra.get("num_layers", 2)
        dropout = self.config.extra.get("dropout", 0.0)
        num_concepts = self.config.extra.get("num_concepts", 8)
        net = _HISTNet(d_feat, hidden_size, num_layers, dropout, num_concepts)
        return net.to(self.config.device)

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model has not been fitted yet")
        self._model.eval()
        with torch.no_grad():
            x_t = torch.from_numpy(np.asarray(x, dtype=np.float32)).to(self.config.device)
            if x_t.dim() == 2:
                x_t = x_t.unsqueeze(0)
            pred = self._model(x_t)
        return pred.cpu().numpy().reshape(-1, self.config.forecast_horizon)

    def fit(self, x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        x = np.asarray(x, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32).ravel()

        if x.ndim == 2:
            x = x[np.newaxis, ...]

        self._model = self.build_model()
        lr = self.config.extra.get("lr", 1e-4)
        self._optimizer = torch.optim.Adam(self._model.parameters(), lr=lr)

        n_epochs = self.config.extra.get("n_epochs", 100)
        batch_size = self.config.extra.get("batch_size", 256)
        device = self.config.device

        dataset = torch.utils.data.TensorDataset(
            torch.from_numpy(x),
            torch.from_numpy(y),
        )
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        self._model.train()
        for _ in range(n_epochs):
            for xb, yb in loader:
                xb = xb.to(device)
                yb = yb.to(device)
                self._optimizer.zero_grad()
                pred = self._model(xb).squeeze(-1)
                loss = self._criterion(pred, yb)
                loss.backward()
                self._optimizer.step()

        self._is_fitted = True
        final_pred = self.predict(x)
        mse = float(np.mean((final_pred.ravel() - y) ** 2))
        return {"loss": mse}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        state = {
            "model": self._model.state_dict() if self._model else None,
            "config": self.config.to_dict(),
        }
        torch.save(state, path)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        state = torch.load(path, map_location=self.config.device, weights_only=False)
        self.config = QlibModelConfig.from_dict(state["config"])
        self._model = self.build_model()
        if state["model"] is not None:
            self._model.load_state_dict(state["model"])
        self._is_fitted = True
        return True
