#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis 管理器 - 量化交易系统 Python 客户端
提供与 Node.js 版本相同的功能
"""

import redis
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class RedisManager:
    """Redis 管理器类，提供量化交易系统所需的功能"""

    def __init__(self):
        """初始化 Redis 管理器"""
        self.client = None
        self.connected = False
        # 使用 WSL2 IP 地址作为默认值，便于 Windows 访问
        self.host = os.getenv("REDIS_HOST", "192.168.18.62")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.password = os.getenv("REDIS_PASSWORD", "")
        self.db = int(os.getenv("REDIS_DB", 0))

    def connect(self) -> bool:
        """
        连接到 Redis

        Returns:
            bool: 连接是否成功
        """
        try:
            if self.password:
                self.client = redis.StrictRedis(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    db=self.db,
                    decode_responses=True
                )
            else:
                self.client = redis.StrictRedis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    decode_responses=True
                )

            # 测试连接
            self.client.ping()
            self.connected = True
            return True

        except Exception as e:
            print("Error: Redis connection failed -", e)
            print("Tip: Please check if Redis is running in WSL2")
            self.connected = False
            return False

    def disconnect(self):
        """断开连接"""
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                print("Error: Failed to disconnect -", e)
            finally:
                self.connected = False
                self.client = None

    # ==================== 数据缓存 ====================

    def cache_kline(self, symbol: str, interval: str, timestamp: int, data: Dict[str, Any]):
        """
        缓存 K 线数据

        Args:
            symbol: 交易对
            interval: 时间周期
            timestamp: 时间戳
            data: K 线数据字典
        """
        if not self.connected:
            if not self.connect():
                return

        key = f"kline:{symbol}:{interval}:{timestamp}"

        try:
            for field, value in data.items():
                self.client.hset(key, field, value)
            self.client.expire(key, 3600)  # 1 hour expiration
        except Exception as e:
            print(f"Error: Failed to cache kline {symbol} {interval}: {e}")

    def get_cached_kline(self, symbol: str, interval: str, timestamp: int) -> Dict[str, str]:
        """
        获取缓存的 K 线数据

        Args:
            symbol: 交易对
            interval: 时间周期
            timestamp: 时间戳

        Returns:
            Dict[str, str]: K 线数据
        """
        if not self.connected:
            if not self.connect():
                return {}

        key = f"kline:{symbol}:{interval}:{timestamp}"

        try:
            return self.client.hgetall(key)
        except Exception as e:
            print(f"Error: Failed to get cached kline {symbol} {interval}: {e}")
            return {}

    # ==================== 策略信号 ====================

    def cache_signal(self, strategy: str, symbol: str, signal: Dict[str, Any]):
        """
        缓存策略信号

        Args:
            strategy: 策略名称
            symbol: 交易对
            signal: 信号数据
        """
        if not self.connected:
            if not self.connect():
                return

        key = f"signal:{strategy}:{symbol}"

        try:
            self.client.setex(key, 60, json.dumps(signal))  # 60 seconds expiration
        except Exception as e:
            print(f"Error: Failed to cache signal {strategy} {symbol}: {e}")

    def get_signal(self, strategy: str, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取策略信号

        Args:
            strategy: 策略名称
            symbol: 交易对

        Returns:
            Optional[Dict]: 信号数据
        """
        if not self.connected:
            if not self.connect():
                return None

        key = f"signal:{strategy}:{symbol}"

        try:
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Error: Failed to get signal {strategy} {symbol}: {e}")
            return None

    # ==================== 订单状态 ====================

    def update_order_status(self, order_id: str, status: str):
        """
        更新订单状态

        Args:
            order_id: 订单 ID
            status: 订单状态
        """
        if not self.connected:
            if not self.connect():
                return

        key = f"order:{order_id}"

        try:
            self.client.hset(key, "status", status)
            self.client.expire(key, 86400)  # 24 hours expiration
        except Exception as e:
            print(f"Error: Failed to update order status {order_id}: {e}")

    def get_order_status(self, order_id: str) -> Optional[str]:
        """
        获取订单状态

        Args:
            order_id: 订单 ID

        Returns:
            Optional[str]: 订单状态
        """
        if not self.connected:
            if not self.connect():
                return None

        key = f"order:{order_id}"

        try:
            return self.client.hget(key, "status")
        except Exception as e:
            print(f"Error: Failed to get order status {order_id}: {e}")
            return None

    # ==================== 统计数据 ====================

    def cache_stats(self, key: str, value: str):
        """
        缓存统计数据

        Args:
            key: 统计键名
            value: 统计值
        """
        if not self.connected:
            if not self.connect():
                return

        try:
            self.client.setex(key, 3600, value)  # 1 hour expiration
        except Exception as e:
            print(f"Error: Failed to cache stats {key}: {e}")

    def get_stats(self, key: str) -> Optional[str]:
        """
        获取统计数据

        Args:
            key: 统计键名

        Returns:
            Optional[str]: 统计值
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            return self.client.get(key)
        except Exception as e:
            print(f"Error: Failed to get stats {key}: {e}")
            return None

    # ==================== 错误计数和熔断 ====================

    def increment_error_count(self, source: str) -> int:
        """
        增量错误计数

        Args:
            source: 错误来源

        Returns:
            int: 错误计数
        """
        if not self.connected:
            if not self.connect():
                return 0

        key = f"error:count:{source}"

        try:
            count = self.client.incr(key)
            self.client.expire(key, 60)  # 1 minute expiration
            return count
        except Exception as e:
            print(f"Error: Failed to increment error count {source}: {e}")
            return 0

    def check_circuit_breaker(self, source: str, threshold: int = 5) -> bool:
        """
        检查熔断器是否触发

        Args:
            source: 错误来源
            threshold: 触发阈值（默认5次）

        Returns:
            bool: 是否触发熔断器
        """
        if not self.connected:
            if not self.connect():
                return False

        key = f"error:count:{source}"

        try:
            count = int(self.client.get(key) or "0")
            return count > threshold
        except Exception as e:
            print(f"Error: Failed to check circuit breaker {source}: {e}")
            return False

    # ==================== 获取 Redis 信息 ====================

    def get_info(self) -> Optional[Dict[str, Any]]:
        """
        获取 Redis 服务器信息

        Returns:
            Optional[Dict]: Redis 信息
        """
        if not self.connected:
            if not self.connect():
                return None

        try:
            info = self.client.info()
            result = {}

            if "server" in info:
                result["Server"] = {
                    "redis_version": info.get("redis_version", "Unknown"),
                    "redis_mode": info.get("redis_mode", "Unknown"),
                    "os": info.get("os", "Unknown")
                }

            if "memory" in info:
                result["Memory"] = {
                    "used_memory_human": info.get("used_memory_human", "Unknown"),
                    "used_memory_peak_human": info.get("used_memory_peak_human", "Unknown"),
                    "maxmemory_human": info.get("maxmemory_human", "0B")
                }

            if "clients" in info:
                result["Clients"] = {
                    "connected_clients": info.get("connected_clients", 0)
                }

            return result

        except Exception as e:
            print(f"Error: Failed to get Redis info: {e}")
            return None

    # ==================== 其他实用方法 ====================

    def ping(self) -> bool:
        """
        测试 Redis 连接

        Returns:
            bool: 连接是否正常
        """
        if not self.connected:
            if not self.connect():
                return False

        try:
            return self.client.ping() == "PONG"
        except Exception:
            return False


# ==================== 使用示例 ====================

def main():
    """测试和使用示例"""
    print("==========================================")
    print("Redis Manager - Quant Trading System (Python)")
    print("==========================================")

    # 创建管理器实例
    manager = RedisManager()

    # 连接 Redis
    print("\nConnecting to Redis...")
    if not manager.connect():
        print("\nTip: Please check if Redis is running in WSL2")
        print("Run: wsl --user root systemctl start redis-server")
        return

    print("OK: Redis connected")

    # 显示 Redis 信息
    info = manager.get_info()
    if info:
        print("\nRedis Server Info:")
        print(f"  Version: {info.get('Server', {}).get('redis_version', 'Unknown')}")
        print(f"  Memory: {info.get('Memory', {}).get('used_memory_human', 'Unknown')}")
        print(f"  Connections: {info.get('Clients', {}).get('connected_clients', 0)}")

    # 运行功能测试
    print("\nRunning functional tests...")

    try:
        # 1. 测试 K 线缓存
        print("\n  Testing K-line cache...")
        manager.cache_kline("BTCUSDT", "1h", int(datetime.now().timestamp()), {
            "open": "70000",
            "high": "71000",
            "low": "69500",
            "close": "70500",
            "volume": "1000"
        })
        print("  OK: K-line cache test passed")

        # 2. 测试策略信号
        print("\n  Testing strategy signal cache...")
        manager.cache_signal("DualMA", "BTCUSDT", {
            "signal": "BUY",
            "price": "70500",
            "timestamp": int(datetime.now().timestamp())
        })
        print("  OK: Signal cache test passed")

        # 3. 测试错误计数
        print("\n  Testing error counting...")
        error_count = manager.increment_error_count("api")
        print(f"  OK: Error count: {error_count}")

        print("\nOK: All tests passed!")

    except Exception as e:
        print(f"\nError: Tests failed - {e}")

    finally:
        manager.disconnect()
        print("\nRedis disconnected")

    print("\nNext steps:")
    print("  1. Configure Redis password in .env file")
    print("  2. Import in your code: from utils.redis_manager import RedisManager")
    print("  3. Reference: Redis在量化交易系统中的应用.md file")


if __name__ == "__main__":
    main()
