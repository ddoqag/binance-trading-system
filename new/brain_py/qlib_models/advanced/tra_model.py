"""
tra_model.py - Qlib TRA benchmark port.

Temporal Routing Adaptor (TRA, KDD 2021).
Simplified port: a single asset with multiple temporal states (market regimes)
routed by a gating network.

Reference hyperparameters (Alpha158):
  tra_config: num_states=3, rnn_arch=LSTM, hidden_size=32, num_layers=1,
              dropout=0.0, tau=1.0
  model_config: input_size=20, hidden_size=64, num_layers=2, rnn_arch=LSTM,
                use_attn=True, dropout=0.0
"""

import os
from typing import Dict, Any
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

from ..base import QlibBaseModel, QlibModelConfig


class _Predictor(nn.Module):
    """Base LSTM/Transformer predictor."""

    def __init__(self, d_feat: int, hidden_size: int, num_layers: int, dropout: float, use_attn: bool = False):
        super().__init__()
        self.rnn = nn.LSTM(
            input_size=d_feat,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.use_attn = use_attn
        if use_attn:
            self.attention = nn.Sequential(
                nn.Linear(hidden_size, hidden_size),
                nn.Tanh(),
                nn.Linear(hidden_size, 1, bias=False),
            )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        out, _ = self.rnn(x)
        if self.use_attn:
            attn = torch.softmax(self.attention(out), dim=1)
            out = torch.sum(attn * out, dim=1)
        else:
            out = out[:, -1, :]
        return self.fc(out)


class _TRARouter(nn.Module):
    """Routing network that assigns input to temporal states."""

    def __init__(self, d_feat: int, hidden_size: int, num_layers: int, num_states: int, dropout: float):
        super().__init__()
        self.rnn = nn.LSTM(
            input_size=d_feat,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(hidden_size, num_states)

    def forward(self, x):
        out, _ = self.rnn(x)
        last = out[:, -1, :]
        logits = self.fc(last)
        return logits


class _TRANet(nn.Module):
    def __init__(
        self,
        d_feat: int,
        hidden_size: int,
        num_layers: int,
        num_states: int,
        dropout: float,
        use_attn: bool = False,
        tau: float = 1.0,
    ):
        super().__init__()
        self.states = nn.ModuleList(
            [_Predictor(d_feat, hidden_size, num_layers, dropout, use_attn) for _ in range(num_states)]
        )
        self.router = _TRARouter(d_feat, hidden_size, 1, num_states, dropout)
        self.tau = tau
        self.num_states = num_states

    def forward(self, x):
        # x: (batch, seq_len, d_feat)
        logits = self.router(x)  # (batch, num_states)
        weights = F.gumbel_softmax(logits, tau=self.tau, hard=False)  # (batch, num_states)

        predictions = torch.stack([state(x).squeeze(-1) for state in self.states], dim=1)  # (batch, num_states)
        output = torch.sum(weights * predictions, dim=1, keepdim=True)
        return output


class TRAModel(QlibBaseModel):
    """TRA model (Temporal Routing Adaptor) simplified port."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="tra",
                input_dim=20,
                lookback_window=20,
                d_feat=20,
                hidden_size=64,
                num_layers=2,
                num_states=3,
                dropout=0.0,
                use_attn=True,
                tau=1.0,
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
        num_states = self.config.extra.get("num_states", 3)
        dropout = self.config.extra.get("dropout", 0.0)
        use_attn = self.config.extra.get("use_attn", True)
        tau = self.config.extra.get("tau", 1.0)
        net = _TRANet(d_feat, hidden_size, num_layers, num_states, dropout, use_attn, tau)
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
