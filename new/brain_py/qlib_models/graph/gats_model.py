"""
gats_model.py - Qlib GATs benchmark port.

Graph Attention Network with LSTM base for temporal features.
Simplified port: we use a learnable attention over a small set of
"synthetic" cross-asset channels instead of a full stock graph.

Reference hyperparameters (Alpha158):
  d_feat=20, hidden_size=64, num_layers=2, dropout=0.7,
  lr=1e-4, base_model=LSTM
"""

import os
from typing import Dict, Any
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

from ..base import QlibBaseModel, QlibModelConfig


class _GATLayer(nn.Module):
    def __init__(self, in_features: int, out_features: int, dropout: float, alpha: float = 0.2):
        super().__init__()
        self.dropout = dropout
        self.in_features = in_features
        self.out_features = out_features
        self.W = nn.Parameter(torch.zeros(size=(in_features, out_features)))
        nn.init.xavier_uniform_(self.W.data)
        self.a = nn.Parameter(torch.zeros(size=(2 * out_features, 1)))
        nn.init.xavier_uniform_(self.a.data)
        self.leakyrelu = nn.LeakyReLU(alpha)

    def forward(self, h):
        # h: (batch, N, in_features) where N is number of nodes/channels
        Wh = torch.matmul(h, self.W)  # (batch, N, out_features)
        e = self._prepare_attentional_mechanism_input(Wh)
        attention = F.softmax(e, dim=2)
        attention = F.dropout(attention, self.dropout, training=self.training)
        h_prime = torch.matmul(attention, Wh)
        return F.elu(h_prime)

    def _prepare_attentional_mechanism_input(self, Wh):
        # Wh: (batch, N, out_features)
        N = Wh.size(1)
        Wh_repeated_in_chunks = Wh.unsqueeze(2).repeat(1, 1, N, 1)
        Wh_repeated_alternating = Wh.unsqueeze(1).repeat(1, N, 1, 1)
        all_combinations_matrix = torch.cat([Wh_repeated_in_chunks, Wh_repeated_alternating], dim=-1)
        return self.leakyrelu(torch.matmul(all_combinations_matrix, self.a).squeeze(-1))


class _GATsNet(nn.Module):
    def __init__(self, d_feat: int, hidden_size: int, num_layers: int, dropout: float, num_channels: int = 4):
        super().__init__()
        # LSTM temporal encoder
        self.lstm = nn.LSTM(
            input_size=d_feat,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        # Project LSTM output into multiple "channels" for graph attention
        self.channel_proj = nn.Linear(hidden_size, num_channels * hidden_size)
        self.gat = _GATLayer(hidden_size, hidden_size, dropout)
        self.fc = nn.Linear(hidden_size * num_channels, 1)
        self.num_channels = num_channels

    def forward(self, x):
        # x: (batch, seq_len, d_feat)
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden_size)
        last = lstm_out[:, -1, :]  # (batch, hidden_size)
        channels = self.channel_proj(last).view(-1, self.num_channels, lstm_out.size(2))
        attended = self.gat(channels)  # (batch, num_channels, hidden_size)
        flat = attended.view(attended.size(0), -1)
        return self.fc(flat)


class GATsModel(QlibBaseModel):
    """GATs model for sequential HFT features (simplified port)."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="gats",
                input_dim=20,
                lookback_window=20,
                d_feat=20,
                hidden_size=64,
                num_layers=2,
                dropout=0.5,
                num_channels=4,
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
        dropout = self.config.extra.get("dropout", 0.5)
        num_channels = self.config.extra.get("num_channels", 4)
        net = _GATsNet(d_feat, hidden_size, num_layers, dropout, num_channels)
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
