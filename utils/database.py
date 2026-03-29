#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库客户端工具
"""

import pandas as pd
from sqlalchemy import create_engine, text
from typing import Optional, Dict, Any
from contextlib import contextmanager


class DatabaseClient:
    """数据库客户端封装"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化数据库客户端

        Args:
            config: 数据库配置字典
        """
        self.config = config
        self.engine = self._create_engine()

    def _create_engine(self):
        """创建数据库引擎"""
        conn_str = (
            f"postgresql://{self.config['user']}:{self.config['password']}"
            f"@{self.config['host']}:{self.config['port']}/{self.config['database']}"
        )
        return create_engine(conn_str)

    @contextmanager
    def connection(self):
        """获取数据库连接的上下文管理器"""
        conn = self.engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        """
        执行查询并返回 DataFrame

        Args:
            query: SQL 查询语句
            params: 查询参数

        Returns:
            查询结果 DataFrame
        """
        with self.connection() as conn:
            return pd.read_sql(text(query), conn, params=params)

    def execute_update(self, query: str, params: Optional[Dict] = None) -> int:
        """
        执行更新/插入/删除操作

        Args:
            query: SQL 语句
            params: 参数

        Returns:
            影响的行数
        """
        with self.connection() as conn:
            result = conn.execute(text(query), params or {})
            conn.commit()
            return result.rowcount

    def load_klines(self, symbol: str, interval: str,
                   start_time: Optional[str] = None,
                   end_time: Optional[str] = None) -> pd.DataFrame:
        """
        加载 K 线数据

        Args:
            symbol: 交易对
            interval: 时间周期
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            K 线数据 DataFrame
        """
        query = """
            SELECT open_time, open, high, low, close, volume
            FROM klines
            WHERE symbol = :symbol AND interval = :interval
        """
        params = {'symbol': symbol, 'interval': interval}

        if start_time:
            query += " AND open_time >= :start_time"
            params['start_time'] = start_time
        if end_time:
            query += " AND open_time <= :end_time"
            params['end_time'] = end_time

        query += " ORDER BY open_time ASC"

        df = self.execute_query(query, params)
        if not df.empty:
            df['open_time'] = pd.to_datetime(df['open_time'])
            df.set_index('open_time', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    def load_indicators(self, symbol: str, interval: str) -> pd.DataFrame:
        """
        加载技术指标数据

        Args:
            symbol: 交易对
            interval: 时间周期

        Returns:
            技术指标 DataFrame
        """
        query = """
            SELECT * FROM technical_indicators
            WHERE symbol = :symbol AND interval = :interval
            ORDER BY open_time ASC
        """
        df = self.execute_query(query, {'symbol': symbol, 'interval': interval})
        if not df.empty:
            df['open_time'] = pd.to_datetime(df['open_time'])
            df.set_index('open_time', inplace=True)
        return df
