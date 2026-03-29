# prepare_training_data.py
"""
合并本地 JSON/CSV 数据，输出标准 OHLCV CSV 供 training_system.train 使用。
"""
import json
import pathlib
import pandas as pd


DATA_DIR = pathlib.Path("data")
OUTPUT = DATA_DIR / "BTCUSDT_1h_training.csv"

# 收集所有 BTCUSDT 1h 文件
files = sorted(DATA_DIR.glob("BTCUSDT-1h-*.json")) + \
        sorted(DATA_DIR.glob("BTCUSDT-1h-*.csv"))

frames = []
for f in files:
    if f.suffix == ".json":
        with open(f) as fp:
            data = json.load(fp)
        df = pd.DataFrame(data)
    else:
        df = pd.read_csv(f)

    # 统一列名
    rename = {
        "openTime": "time",
        "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume",
    }
    df = df.rename(columns=rename)
    frames.append(df[["time", "open", "high", "low", "close", "volume"]])

combined = (
    pd.concat(frames)
    .drop_duplicates("time")
    .sort_values("time")
    .reset_index(drop=True)
)

# 确保数值列是 float
for col in ["open", "high", "low", "close", "volume"]:
    combined[col] = combined[col].astype(float)

combined.to_csv(OUTPUT, index=False)
print(f"✓ 保存到 {OUTPUT}  ({len(combined)} 行)")
print(f"  时间范围: {combined.time.iloc[0]} → {combined.time.iloc[-1]}")
