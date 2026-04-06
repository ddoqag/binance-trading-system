"""
诊断价格获取问题
"""
import asyncio
import sys
import os
import json

# 添加项目路径
sys.path.insert(0, 'D:/binance/new')

from core.binance_ws_client import BinanceWSClient
from core.binance_rest_client import BinanceRESTClient

def check_websocket_price():
    """检查 WebSocket 价格获取"""
    print("=" * 60)
    print("WebSocket 价格获取诊断")
    print("=" * 60)

    # 创建 WebSocket 客户端
    ws_client = BinanceWSClient("BTCUSDT")

    # 检查初始状态
    print(f"\n1. 初始状态:")
    print(f"   ws_client.book: {ws_client.book}")
    print(f"   ws_client.last_price: {ws_client.last_price}")

    # 启动 WebSocket
    print(f"\n2. 启动 WebSocket...")
    ws_client.start()

    # 等待数据接收
    import time
    print(f"\n3. 等待 5 秒接收数据...")
    time.sleep(5)

    # 检查接收后的状态
    print(f"\n4. 接收后的状态:")
    print(f"   ws_client.book: {ws_client.book}")
    if ws_client.book:
        print(f"   book.bids: {ws_client.book.bids[:2] if ws_client.book.bids else 'Empty'}")
        print(f"   book.asks: {ws_client.book.asks[:2] if ws_client.book.asks else 'Empty'}")
        print(f"   book.best_bid(): {ws_client.book.best_bid()}")
        print(f"   book.best_ask(): {ws_client.book.best_ask()}")
        print(f"   book.mid_price(): {ws_client.book.mid_price()}")
    else:
        print(f"   book is None - WebSocket 未接收到数据!")

    print(f"   ws_client.last_price: {ws_client.last_price}")

    # 停止 WebSocket
    ws_client.stop()
    print(f"\n5. WebSocket 已停止")

def check_rest_api_price():
    """检查 REST API 价格获取"""
    print("\n" + "=" * 60)
    print("REST API 价格获取诊断")
    print("=" * 60)

    try:
        rest_client = BinanceRESTClient(use_testnet=True)
        print(f"\n1. REST 客户端创建成功")

        # 获取 ticker
        ticker = rest_client.get_ticker("BTCUSDT")
        print(f"\n2. Ticker 数据:")
        if ticker:
            print(f"   lastPrice: {ticker.get('lastPrice')}")
            print(f"   bidPrice: {ticker.get('bidPrice')}")
            print(f"   askPrice: {ticker.get('askPrice')}")
        else:
            print(f"   无法获取 ticker 数据!")

    except Exception as e:
        print(f"\n   REST API 错误: {e}")

def check_signal_stats():
    """检查信号统计文件"""
    print("\n" + "=" * 60)
    print("信号统计文件诊断")
    print("=" * 60)

    stats_file = "D:/binance/new/signal_stats_verify.json"
    if os.path.exists(stats_file):
        with open(stats_file, 'r') as f:
            data = json.load(f)

        history = data.get('history', [])
        print(f"\n1. 统计记录数: {len(history)}")

        if history:
            # 检查价格数据
            prices = [h.get('current_price') for h in history if h.get('current_price')]
            print(f"\n2. 有价格数据的记录: {len(prices)}/{len(history)}")

            if prices:
                print(f"   最新价格: {prices[-1]}")
            else:
                print(f"   所有记录的价格都是 null!")

            # 检查信号触发
            triggers = [h for h in history if h.get('would_trigger')]
            print(f"\n3. 信号触发次数: {len(triggers)}")

            # 显示最新记录
            print(f"\n4. 最新记录:")
            latest = history[-1]
            print(f"   timestamp: {latest.get('timestamp')}")
            print(f"   current_price: {latest.get('current_price')}")
            print(f"   net_strength: {latest.get('net_strength')}")
            print(f"   threshold: {latest.get('threshold')}")
            print(f"   would_trigger: {latest.get('would_trigger')}")
    else:
        print(f"\n   统计文件不存在: {stats_file}")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("价格获取问题诊断工具")
    print("=" * 60)

    # 检查信号统计
    check_signal_stats()

    # 检查 REST API
    check_rest_api_price()

    # 检查 WebSocket
    check_websocket_price()

    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)
