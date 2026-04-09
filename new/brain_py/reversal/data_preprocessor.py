"""
data_preprocessor.py - 数据预处理流程

提供完整的数据预处理管道：
1. 数据清洗 (缺失值、异常值处理)
2. 特征标准化/归一化
3. 滞后特征生成
4. 训练/验证/测试集分割 (时序-aware)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PreprocessConfig:
    """预处理配置"""
    # 缺失值处理
    fill_missing: str = "forward"  # "forward", "backward", "mean", "zero"
    max_missing_ratio: float = 0.1

    # 异常值处理
    outlier_method: str = "clip"  # "clip", "remove", "none"
    outlier_std_threshold: float = 5.0

    # 标准化方法
    scaler_type: str = "standard"  # "standard", "minmax", "robust", "none"

    # 滞后特征
    lag_periods: List[int] = None

    # 时间分割比例
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    test_ratio: float = 0.15

    def __post_init__(self):
        if self.lag_periods is None:
            self.lag_periods = [1, 2, 3]
        assert abs(self.train_ratio + self.val_ratio + self.test_ratio - 1.0) < 1e-6, \
            "Ratios must sum to 1.0"


class DataPreprocessor:
    """
    数据预处理器

    处理原始数据并准备机器学习输入
    """

    def __init__(self, config: Optional[PreprocessConfig] = None):
        self.config = config or PreprocessConfig()
        self.scaler: Optional[Union[StandardScaler, MinMaxScaler, RobustScaler]] = None
        self.feature_names: List[str] = []
        self.target_column: Optional[str] = None

    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗数据

        Args:
            df: 原始DataFrame

        Returns:
            清洗后的DataFrame
        """
        df = df.copy()
        initial_rows = len(df)

        # 1. 处理缺失值
        missing_ratio = df.isnull().mean()

        # 删除缺失值过多的列
        cols_to_drop = missing_ratio[missing_ratio > self.config.max_missing_ratio].index
        if len(cols_to_drop) > 0:
            logger.warning(f"Dropping columns with too many NaN: {list(cols_to_drop)}")
            df = df.drop(columns=cols_to_drop)

        # 填充剩余缺失值
        if self.config.fill_missing == "forward":
            df = df.fillna(method="ffill").fillna(method="bfill")
        elif self.config.fill_missing == "backward":
            df = df.fillna(method="bfill").fillna(method="ffill")
        elif self.config.fill_missing == "mean":
            df = df.fillna(df.mean())
        elif self.config.fill_missing == "zero":
            df = df.fillna(0)

        # 2. 处理异常值
        if self.config.outlier_method == "clip":
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            for col in numeric_cols:
                mean = df[col].mean()
                std = df[col].std()
                lower = mean - self.config.outlier_std_threshold * std
                upper = mean + self.config.outlier_std_threshold * std
                df[col] = df[col].clip(lower, upper)
        elif self.config.outlier_method == "remove":
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            mask = pd.Series(True, index=df.index)
            for col in numeric_cols:
                mean = df[col].mean()
                std = df[col].std()
                lower = mean - self.config.outlier_std_threshold * std
                upper = mean + self.config.outlier_std_threshold * std
                mask &= (df[col] >= lower) & (df[col] <= upper)
            df = df[mask]

        logger.info(f"Data cleaning: {initial_rows} -> {len(df)} rows")
        return df

    def create_lag_features(
        self,
        df: pd.DataFrame,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        创建滞后特征

        Args:
            df: 输入DataFrame
            columns: 要创建滞后的列，None表示所有数值列

        Returns:
            包含滞后特征的DataFrame
        """
        if columns is None:
            columns = df.select_dtypes(include=[np.number]).columns.tolist()

        result = df.copy()

        for col in columns:
            for lag in self.config.lag_periods:
                result[f"{col}_lag_{lag}"] = df[col].shift(lag)

        # 删除因滞后产生的NaN行
        result = result.dropna()

        logger.info(f"Created {len(self.config.lag_periods)} lag features for {len(columns)} columns")
        return result

    def fit_scaler(self, df: pd.DataFrame, feature_cols: List[str]) -> None:
        """
        拟合标准化器

        Args:
            df: 训练数据
            feature_cols: 特征列名
        """
        if self.config.scaler_type == "standard":
            self.scaler = StandardScaler()
        elif self.config.scaler_type == "minmax":
            self.scaler = MinMaxScaler(feature_range=(-1, 1))
        elif self.config.scaler_type == "robust":
            self.scaler = RobustScaler()
        else:
            return

        self.scaler.fit(df[feature_cols])
        self.feature_names = feature_cols
        logger.info(f"Fitted {self.config.scaler_type} scaler on {len(feature_cols)} features")

    def transform(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
        """
        转换数据

        Args:
            df: 输入DataFrame
            feature_cols: 特征列名

        Returns:
            标准化后的DataFrame
        """
        if self.scaler is None:
            return df

        df = df.copy()
        df[feature_cols] = self.scaler.transform(df[feature_cols])
        return df

    def fit_transform(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
    ) -> pd.DataFrame:
        """
        拟合并转换数据

        Args:
            df: 输入DataFrame
            feature_cols: 特征列名

        Returns:
            标准化后的DataFrame
        """
        self.fit_scaler(df, feature_cols)
        return self.transform(df, feature_cols)

    def time_series_split(
        self,
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        时序数据分割

        按时间顺序分割，避免数据泄露

        Args:
            df: 输入DataFrame

        Returns:
            (train_df, val_df, test_df)
        """
        n = len(df)
        train_end = int(n * self.config.train_ratio)
        val_end = int(n * (self.config.train_ratio + self.config.val_ratio))

        train_df = df.iloc[:train_end].copy()
        val_df = df.iloc[train_end:val_end].copy()
        test_df = df.iloc[val_end:].copy()

        logger.info(
            f"Time series split: train={len(train_df)}, "
            f"val={len(val_df)}, test={len(test_df)}"
        )
        return train_df, val_df, test_df

    def prepare_features_and_labels(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        label_col: str,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        准备特征和标签

        Args:
            df: 输入DataFrame
            feature_cols: 特征列名
            label_col: 标签列名

        Returns:
            (X, y) numpy arrays
        """
        X = df[feature_cols].values
        y = df[label_col].values
        return X, y

    def preprocess_pipeline(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        label_col: str,
        create_lags: bool = True,
    ) -> Dict[str, Union[pd.DataFrame, np.ndarray]]:
        """
        完整预处理管道

        Args:
            df: 原始数据
            feature_cols: 特征列名
            label_col: 标签列名
            create_lags: 是否创建滞后特征

        Returns:
            包含训练/验证/测试数据的字典
        """
        # 1. 数据清洗
        df = self.clean_data(df)

        # 2. 创建滞后特征
        if create_lags:
            df = self.create_lag_features(df, feature_cols)
            # 更新特征列名
            lagged_cols = [c for c in df.columns if "_lag_" in c]
            feature_cols = feature_cols + lagged_cols

        # 3. 时序分割
        train_df, val_df, test_df = self.time_series_split(df)

        # 4. 标准化 (只在训练集上拟合)
        train_df = self.fit_transform(train_df, feature_cols)
        val_df = self.transform(val_df, feature_cols)
        test_df = self.transform(test_df, feature_cols)

        # 5. 准备numpy数组
        X_train, y_train = self.prepare_features_and_labels(train_df, feature_cols, label_col)
        X_val, y_val = self.prepare_features_and_labels(val_df, feature_cols, label_col)
        X_test, y_test = self.prepare_features_and_labels(test_df, feature_cols, label_col)

        return {
            "train_df": train_df,
            "val_df": val_df,
            "test_df": test_df,
            "X_train": X_train,
            "y_train": y_train,
            "X_val": X_val,
            "y_val": y_val,
            "X_test": X_test,
            "y_test": y_test,
            "feature_cols": feature_cols,
            "label_col": label_col,
        }

    def save_scaler(self, path: str) -> None:
        """保存标准化器"""
        import pickle
        if self.scaler is not None:
            with open(path, "wb") as f:
                pickle.dump({
                    "scaler": self.scaler,
                    "feature_names": self.feature_names,
                    "config": self.config,
                }, f)
            logger.info(f"Scaler saved to {path}")

    def load_scaler(self, path: str) -> None:
        """加载标准化器"""
        import pickle
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.scaler = data["scaler"]
        self.feature_names = data["feature_names"]
        self.config = data["config"]
        logger.info(f"Scaler loaded from {path}")


def create_preprocessor(
    scaler_type: str = "standard",
    lag_periods: Optional[List[int]] = None,
) -> DataPreprocessor:
    """
    创建预处理器便捷函数

    Args:
        scaler_type: 标准化类型
        lag_periods: 滞后周期

    Returns:
        DataPreprocessor实例
    """
    config = PreprocessConfig(
        scaler_type=scaler_type,
        lag_periods=lag_periods or [1, 2, 3],
    )
    return DataPreprocessor(config)


def merge_features_and_labels(
    features_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    drop_na: bool = True,
) -> pd.DataFrame:
    """
    合并特征和标签

    Args:
        features_df: 特征DataFrame
        labels_df: 标签DataFrame
        drop_na: 是否删除NaN行

    Returns:
        合并后的DataFrame
    """
    merged = pd.concat([features_df, labels_df], axis=1)
    if drop_na:
        merged = merged.dropna()
    return merged
