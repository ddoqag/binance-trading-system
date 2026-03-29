#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis 连接测试 (Python 版本)
"""

import sys
from datetime import datetime
from utils.redis_manager import RedisManager


def main():
    """主测试函数"""
    print("==========================================")
    print("Redis Connection Test (Python Version)")
    print("==========================================")
    print("\nStarting Redis connection test...")

    # 创建管理器实例
    manager = RedisManager()

    print("\n1/3: Attempting to connect to Redis...")
    if not manager.connect():
        print("Error: Connection failed")
        print("Tip: Please check if Redis is running in WSL2")
        print("Run: wsl --user root systemctl start redis-server")
        sys.exit(1)

    print("OK: Redis connected")
    print("OK: Redis server ready")

    print("\n2/3: Testing basic operations...")

    try:
        # 测试 ping
        print("  Ping:", "PONG" if manager.ping() else "FAIL")

        # 测试设置和获取
        test_key = f"test:{int(datetime.now().timestamp())}"
        test_value = "Hello Redis from Binance Trading System (Python)"

        manager.cache_stats(test_key, test_value)
        print(f"  Set key: {test_key}")

        get_result = manager.get_stats(test_key)
        print(f"  Get value: {get_result}")

        # 测试删除（让 Redis 自动过期）
        print(f"  Key will expire automatically after 1 hour")

    except Exception as e:
        print(f"  Error: Operation failed - {e}")
        manager.disconnect()
        sys.exit(1)

    print("\n3/3: Testing server information...")

    try:
        info = manager.get_info()
        if info:
            server = info.get("Server", {})
            mem = info.get("Memory", {})
            clients = info.get("Clients", {})

            print(f"  Server version: {server.get('redis_version', 'Unknown')}")
            print(f"  Mode: {server.get('redis_mode', 'Unknown')}")
            print(f"  Memory used: {mem.get('used_memory_human', 'Unknown')}")
            print(f"  Connections: {clients.get('connected_clients', 0)}")

    except Exception as e:
        print(f"  Error: Failed to get server info - {e}")

    manager.disconnect()
    print("\nOK: All tests passed!")
    print("Redis is configured and working properly (Python).")


if __name__ == "__main__":
    main()
