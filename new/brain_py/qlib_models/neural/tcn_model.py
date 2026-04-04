"""
tcn_model.py - Qlib TCN benchmark port.

Temporal Convolutional Network with dilated causal convolutions.
Reference hyperparameters (Alpha158):
  d_feat=20, num_layers=5, n_chans=32, kernel_size=7,
  dropout=0.5, lr=1e-4, batch_size=2000, n_epochs=200, step_len=20
"""

import os
from typing import Dict, Any
import numpy as np

import torch
import torch.nn as nn

from ..base import QlibBaseModel, QlibModelConfig


class _Chomp1d(nn.Module):
    def __init__(self, chomp_size: int):
        super().__init__()
        self.chomp_size = chomp_size

    def forward(self, x):
        return x[:, :, : -self.chomp_size]


class _TemporalBlock(nn.Module):
    def __init__(self, n_inputs: int, n_outputs: int, kernel_size: int, stride: int, dilation: int, dropout: float):
        super().__init__()
        padding = (kernel_size - 1) * dilation
        self.conv1 = nn.Conv1d(n_inputs, n_outputs, kernel_size, stride=stride, padding=padding, dilation=dilation)
        self.chomp1 = _Chomp1d(padding)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)

        self.conv2 = nn.Conv1d(n_outputs, n_outputs, kernel_size, stride=stride, padding=padding, dilation=dilation)
        self.chomp2 = _Chomp1d(padding)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)

        self.net = nn.Sequential(
            self.conv1,
            self.chomp1,
            self.relu1,
            self.dropout1,
            self.conv2,
            self.chomp2,
            self.relu2,
            self.dropout2,
        )
        self.downsample = nn.Conv1d(n_inputs, n_outputs, 1) if n_inputs != n_outputs else None
        self.relu = nn.ReLU()

    def forward(self, x):
        out = self.net(x)
        res = x if self.downsample is None else self.downsample(x)
        return self.relu(out + res)


class _TCNet(nn.Module):
    def __init__(self, d_feat: int, num_layers: int, n_chans: int, kernel_size: int, dropout: float):
        super().__init__()
        layers = []
        for i in range(num_layers):
            in_channels = d_feat if i == 0 else n_chans
            out_channels = n_chans
            dilation = 2 ** i
            layers.append(
                _TemporalBlock(
                    in_channels, out_channels, kernel_size, stride=1, dilation=dilation, dropout=dropout
                )
            )
        self.network = nn.Sequential(*layers)
        self.fc = nn.Linear(n_chans, 1)

    def forward(self, x):
        # x: (batch, seq_len, d_feat) -> (batch, d_feat, seq_len)
        x = x.transpose(1, 2)
        out = self.network(x)
        # Use last time step: (batch, n_chans, seq_len) -> (batch, n_chans)
        last = out[:, :, -1]
        return self.fc(last).squeeze(-1)


class TCNModel(QlibBaseModel):
    """TCN model for sequential HFT features."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="tcn",
                input_dim=20,
                lookback_window=20,
                d_feat=20,
                num_layers=5,
                n_chans=32,
                kernel_size=7,
                dropout=0.5,
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
        num_layers = self.config.extra.get("num_layers", 5)
        n_chans = self.config.extra.get("n_chans", 32)
        kernel_size = self.config.extra.get("kernel_size", 7)
        dropout = self.config.extra.get("dropout", 0.5)
        net = _TCNet(d_feat, num_layers, n_chans, kernel_size, dropout)
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
