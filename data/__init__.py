"""
Data Module - 数据模块
提供统一的数据加载接口
"""

from data.loader import (
    DataLoader,
    load_csv_data,
    load_json_data,
    load_from_database,
    save_dataframe
)

__all__ = [
    'DataLoader',
    'load_csv_data',
    'load_json_data',
    'load_from_database',
    'save_dataframe',
]
