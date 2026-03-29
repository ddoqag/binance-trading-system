# training_system/train.py
"""
Training entry point for the LightGBM signal model.

Usage (CSV):
    python -m training_system.train --csv data/BTCUSDT_1h.csv --out models/lgbm_btc.txt

Usage (数据库):
    python -m training_system.train --db --symbol BTCUSDT --interval 1h --out models/lgbm_btc.txt

The script:
  1. Loads OHLCV CSV
  2. Builds features + labels
  3. Runs Optuna hyperparameter search over walk-forward windows
  4. Retrains on full dataset with best params
  5. Saves model to disk
  6. Prints evaluation summary
"""
from __future__ import annotations
import argparse
import logging
import pathlib

import numpy as np
import optuna
import pandas as pd

from training_system.dataset import build_dataset
from training_system.evaluate import evaluate_predictions
from training_system.model import train_lgbm
from training_system.objective import LGBMObjective
from training_system.walkforward import walk_forward_splits

logger = logging.getLogger(__name__)

optuna.logging.set_verbosity(optuna.logging.WARNING)


def train(
    output_path: str,
    csv_path: str | None = None,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    db_limit: int = 2000,
    n_trials: int = 30,
    horizon: int = 10,
    threshold: float = 0.005,
    train_size: int = 1000,
    test_size: int = 200,
) -> None:
    """End-to-end train + save pipeline."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # ── 1. Load data ─────────────────────────────────────────────────────────
    if csv_path:
        logger.info("Loading data from CSV: %s", csv_path)
        df = pd.read_csv(csv_path)
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"CSV is missing columns: {missing}")
    else:
        from training_system.db_loader import load_klines
        logger.info("Loading data from DB: %s %s", symbol, interval)
        df = load_klines(symbol=symbol, interval=interval, limit=db_limit)

    # ── 2. Build dataset ─────────────────────────────────────────────────────
    logger.info("Building features + labels ...")
    X, y = build_dataset(df, horizon=horizon, threshold=threshold)
    logger.info("Dataset shape: X=%s  y=%s  pos_rate=%.2f%%",
                X.shape, y.shape, 100 * y.mean())

    if X.shape[0] < train_size + test_size:
        raise ValueError(
            f"Not enough data ({X.shape[0]} rows) for train_size={train_size} + test_size={test_size}"
        )

    # ── 3. Hyperparameter search ──────────────────────────────────────────────
    logger.info("Running Optuna search (%d trials) ...", n_trials)
    objective = LGBMObjective(X, y, train_size=train_size, test_size=test_size)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best_params = study.best_params
    logger.info("Best params: %s  (AUC=%.4f)", best_params, study.best_value)

    # ── 4. Final model on full data ───────────────────────────────────────────
    logger.info("Training final model on full dataset ...")
    model = train_lgbm(X, y, params=dict(best_params))

    # ── 5. Save model ─────────────────────────────────────────────────────────
    out = pathlib.Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(out))
    logger.info("Model saved to %s", out)

    # ── 6. In-sample evaluation (diagnostic only — not for production use) ────
    probs = model.predict(X)
    metrics = evaluate_predictions(y, probs)
    logger.info(
        "In-sample metrics | acc=%.3f  auc=%.3f  sharpe=%.2f",
        metrics["accuracy"], metrics["auc"], metrics["sharpe"],
    )

    # Out-of-sample summary over last walk-forward window
    splits = list(walk_forward_splits(X, y, train_size=train_size, test_size=test_size))
    if splits:
        *_, X_te, y_te = splits[-1]
        probs_oos = model.predict(X_te)
        oos = evaluate_predictions(y_te, probs_oos)
        logger.info(
            "Last OOS window     | acc=%.3f  auc=%.3f  sharpe=%.2f",
            oos["accuracy"], oos["auc"], oos["sharpe"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train LightGBM signal model")
    parser.add_argument("--csv", default=None, help="Path to OHLCV CSV file")
    parser.add_argument("--db", action="store_true", help="Load from PostgreSQL instead of CSV")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading symbol (default BTCUSDT)")
    parser.add_argument("--interval", default="1h", help="K-line interval (default 1h)")
    parser.add_argument("--db-limit", type=int, default=2000, dest="db_limit", help="Max rows from DB (default 2000)")
    parser.add_argument("--out", required=True, help="Output path for model file (.txt)")
    parser.add_argument("--trials", type=int, default=30, help="Optuna trials (default 30)")
    parser.add_argument("--train-size", type=int, default=1000, dest="train_size", help="WF train window (default 1000)")
    parser.add_argument("--test-size", type=int, default=200, dest="test_size", help="WF test window (default 200)")
    parser.add_argument("--horizon", type=int, default=10, help="Label horizon bars (default 10)")
    parser.add_argument("--threshold", type=float, default=0.005, help="Label threshold (default 0.005)")
    args = parser.parse_args()

    train(
        output_path=args.out,
        csv_path=args.csv if not args.db else None,
        symbol=args.symbol,
        interval=args.interval,
        db_limit=args.db_limit,
        n_trials=args.trials,
        horizon=args.horizon,
        threshold=args.threshold,
        train_size=args.train_size,
        test_size=args.test_size,
    )


if __name__ == "__main__":
    main()
