"""
alstm_model.py - Qlib ALSTM benchmark port.

Attention-enhanced LSTM/GRU (Yao Qin, IJCAI 2017).
Reference hyperparameters (Alpha158):
  d_feat=20, hidden_size=64, num_layers=2, dropout=0.0,
  lr=1e-3, batch_size=800, rnn_type=GRU, n_epochs=200
"""

import os
from typing import Dict, Any
import numpy as np

import torch
import torch.nn as nn

from ..base import QlibBaseModel, QlibModelConfig


class _ALSTMNet(nn.Module):
    def __init__(
        self,
        d_feat: int,
        hidden_size: int,
        num_layers: int,
        dropout: float,
        rnn_type: str = "GRU",
    ):
        super().__init__()
        rnn_cls = nn.GRU if rnn_type.upper() == "GRU" else nn.LSTM
        self.rnn = rnn_cls(
            input_size=d_feat,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.attention = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 1, bias=False),
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        # x: (batch, seq_len, d_feat)
        rnn_out, _ = self.rnn(x)  # (batch, seq_len, hidden_size)

        # Temporal attention over all time steps
        attn_scores = self.attention(rnn_out)  # (batch, seq_len, 1)
        attn_weights = torch.softmax(attn_scores, dim=1)
        context = torch.sum(attn_weights * rnn_out, dim=1)  # (batch, hidden_size)

        return self.fc(context)


class ALSTMModel(QlibBaseModel):
    """ALSTM model for sequential HFT features."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="alstm",
                input_dim=20,
                lookback_window=20,
                d_feat=20,
                hidden_size=64,
                num_layers=2,
                dropout=0.0,
                rnn_type="GRU",
                lr=1e-3,
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
        rnn_type = self.config.extra.get("rnn_type", "GRU")
        net = _ALSTMNet(d_feat, hidden_size, num_layers, dropout, rnn_type)
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
        lr = self.config.extra.get("lr", 1e-3)
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
