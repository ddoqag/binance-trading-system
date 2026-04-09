"""
model_trainer.py - Training script for ReversalAlphaModel.

This script:
1. Loads historical data from PostgreSQL or CSV
2. Generates features using feature_pipeline
3. Generates labels using label_generator
4. Trains the LightGBM model with time series CV
5. Evaluates and saves the model
6. Exports to ONNX format
"""

import os
import sys
import argparse
import logging
from typing import Optional
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reversal.reversal_model import ReversalAlphaModel, ReversalModelConfig

try:
    from reversal.feature_pipeline import FeaturePipeline
except ImportError:
    FeaturePipeline = None
    logging.warning("feature_pipeline not found, will use synthetic features")

try:
    from reversal.label_generator import LabelGenerator
except ImportError:
    LabelGenerator = None
    logging.warning("label_generator not found, will use synthetic labels")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default database configuration
DEFAULT_DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "binance"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "362232"),
}


def load_data_from_db(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    lookback_days: int = 365,
    db_config: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Load historical klines data from PostgreSQL.

    Args:
        symbol: Trading pair symbol
        interval: Time interval (1m, 5m, 15m, 1h, 4h, 1d)
        lookback_days: Number of days to look back
        db_config: Database configuration

    Returns:
        DataFrame with OHLCV data
    """
    if psycopg2 is None:
        raise ImportError("psycopg2 not installed. Run: pip install psycopg2-binary")

    config = db_config or DEFAULT_DB_CONFIG

    end_time = datetime.now()
    start_time = end_time - timedelta(days=lookback_days)

    query = """
        SELECT open_time, open, high, low, close, volume,
               quote_volume, trades, taker_buy_volume
        FROM klines
        WHERE symbol = %s
          AND interval = %s
          AND open_time >= %s
          AND open_time <= %s
        ORDER BY open_time ASC
    """

    conn = psycopg2.connect(**config)
    try:
        df = pd.read_sql_query(
            query,
            conn,
            params=(symbol, interval, start_time, end_time),
        )
        logger.info(f"Loaded {len(df)} rows from database")
        return df
    finally:
        conn.close()


def load_data_from_csv(csv_path: str) -> pd.DataFrame:
    """
    Load historical data from CSV file.

    Expected columns: open_time, open, high, low, close, volume
    """
    df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(df)} rows from {csv_path}")
    return df


def generate_synthetic_features(n_samples: int = 5000, n_features: int = 20) -> np.ndarray:
    """Generate synthetic features for testing."""
    np.random.seed(42)
    return np.random.randn(n_samples, n_features).astype(np.float32)


def generate_synthetic_labels(n_samples: int = 5000, reversal_rate: float = 0.3) -> np.ndarray:
    """Generate synthetic labels for testing."""
    np.random.seed(42)
    return (np.random.rand(n_samples) < reversal_rate).astype(np.int32)


def train_model(
    data_source: str = "synthetic",
    csv_path: Optional[str] = None,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    lookback_days: int = 365,
    use_cv: bool = True,
    output_dir: str = "checkpoints",
) -> None:
    """
    Main training function.

    Args:
        data_source: "synthetic", "csv", or "db"
        csv_path: Path to CSV file if data_source="csv"
        symbol: Trading pair symbol
        interval: Time interval
        lookback_days: Days of history to load
        use_cv: Whether to use cross-validation
        output_dir: Directory to save model
    """
    logger.info("=" * 60)
    logger.info("ReversalAlphaModel Training")
    logger.info("=" * 60)

    # Load data
    logger.info(f"Loading data from source: {data_source}")

    if data_source == "synthetic":
        X = generate_synthetic_features(n_samples=5000, n_features=20)
        y = generate_synthetic_labels(n_samples=5000, reversal_rate=0.3)
        feature_names = [f"feature_{i}" for i in range(20)]
    elif data_source == "csv":
        if csv_path is None:
            raise ValueError("csv_path required when data_source='csv'")
        df = load_data_from_csv(csv_path)

        # Generate features and labels
        if FeaturePipeline is not None and LabelGenerator is not None:
            logger.info("Generating features using FeaturePipeline")
            feature_pipe = FeaturePipeline()
            X = feature_pipe.transform(df)

            logger.info("Generating labels using LabelGenerator")
            label_gen = LabelGenerator()
            y = label_gen.generate_labels(df)
            feature_names = feature_pipe.get_feature_names()
        else:
            logger.warning("FeaturePipeline/LabelGenerator not available, using synthetic")
            X = generate_synthetic_features(n_samples=len(df), n_features=20)
            y = generate_synthetic_labels(n_samples=len(df), reversal_rate=0.3)
            feature_names = [f"feature_{i}" for i in range(20)]
    elif data_source == "db":
        df = load_data_from_db(symbol, interval, lookback_days)

        # Generate features and labels
        if FeaturePipeline is not None and LabelGenerator is not None:
            logger.info("Generating features using FeaturePipeline")
            feature_pipe = FeaturePipeline()
            X = feature_pipe.transform(df)

            logger.info("Generating labels using LabelGenerator")
            label_gen = LabelGenerator()
            y = label_gen.generate_labels(df)
            feature_names = feature_pipe.get_feature_names()
        else:
            logger.warning("FeaturePipeline/LabelGenerator not available, using synthetic")
            X = generate_synthetic_features(n_samples=len(df), n_features=20)
            y = generate_synthetic_labels(n_samples=len(df), reversal_rate=0.3)
            feature_names = [f"feature_{i}" for i in range(20)]
    else:
        raise ValueError(f"Unknown data_source: {data_source}")

    logger.info(f"Feature matrix shape: {X.shape}")
    logger.info(f"Label distribution: {np.bincount(y)}")

    # Create model
    config = ReversalModelConfig(
        num_leaves=31,
        learning_rate=0.05,
        n_estimators=500,
        feature_fraction=0.9,
        bagging_fraction=0.8,
        early_stopping_rounds=50,
    )

    model = ReversalAlphaModel(config)

    # Train
    if use_cv:
        logger.info("Training with time series cross-validation")
        results = model.train_cv(X, y, feature_names=feature_names)

        logger.info("\n" + "=" * 40)
        logger.info("Cross-Validation Results")
        logger.info("=" * 40)
        for fold_metric in results["fold_metrics"]:
            logger.info(
                f"Fold {fold_metric['fold']}: AUC={fold_metric['auc']:.4f}, "
                f"Accuracy={fold_metric['accuracy']:.4f}, "
                f"F1={fold_metric['f1']:.4f}"
            )
        logger.info(f"Mean AUC: {results['mean_auc']:.4f} (+/- {results['std_auc']:.4f})")
        logger.info(f"Mean Accuracy: {results['mean_accuracy']:.4f}")
    else:
        logger.info("Training without cross-validation")
        metrics = model.train(X, y, feature_names=feature_names)

        logger.info("\n" + "=" * 40)
        logger.info("Training Results")
        logger.info("=" * 40)
        for metric, value in metrics.items():
            logger.info(f"{metric}: {value:.4f}")

    # Feature importance
    importance = model.get_feature_importance()
    if importance:
        logger.info("\n" + "=" * 40)
        logger.info("Top 10 Feature Importances")
        logger.info("=" * 40)
        sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)
        for name, imp in sorted_importance[:10]:
            logger.info(f"{name}: {imp:.4f}")

    # Save model with timestamp
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save in pickle format (full Python object)
    pkl_path = os.path.join(output_dir, "reversal_model.pkl")
    model.save_model(pkl_path, timestamp=timestamp)

    # Save in LightGBM native text format (for Go/C++ API)
    txt_path = os.path.join(output_dir, "reversal_model.txt")
    model.save_model_txt(txt_path, timestamp=timestamp)

    # Export to ONNX format
    onnx_path = os.path.join(output_dir, "reversal_model.onnx")
    try:
        model.export_to_onnx(onnx_path, input_dim=X.shape[1], timestamp=timestamp)
        logger.info(f"ONNX model exported to {onnx_path}_{timestamp}.onnx")
    except ImportError as e:
        logger.warning(f"Failed to export to ONNX: {e}. Install: pip install onnxmltools")

    # Test inference
    logger.info("\n" + "=" * 40)
    logger.info("Testing Inference")
    logger.info("=" * 40)

    test_samples = X[:5]
    probs = model.predict_proba(test_samples)
    signals = model.predict_signal_strength(test_samples)

    for i in range(5):
        logger.info(f"Sample {i+1}: prob={probs[i]:.4f}, signal={signals[i]:.4f}")

    logger.info("\n" + "=" * 60)
    logger.info("Training Complete!")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Train ReversalAlphaModel")
    parser.add_argument(
        "--data-source",
        choices=["synthetic", "csv", "db"],
        default="synthetic",
        help="Data source for training"
    )
    parser.add_argument(
        "--csv-path",
        type=str,
        help="Path to CSV file (required if data_source=csv)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading pair symbol"
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1h",
        help="Time interval"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Days of history to load"
    )
    parser.add_argument(
        "--no-cv",
        action="store_true",
        help="Disable cross-validation"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="checkpoints",
        help="Directory to save model"
    )

    args = parser.parse_args()

    train_model(
        data_source=args.data_source,
        csv_path=args.csv_path,
        symbol=args.symbol,
        interval=args.interval,
        lookback_days=args.lookback_days,
        use_cv=not args.no_cv,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
