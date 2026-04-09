"""
MarketMakerV1 纸交易集成测试脚本。
此脚本模拟一个简化的主循环，从Go引擎获取市场数据，并驱动MM策略。
"""
import time
import json
import sys
from typing import Dict, Any
from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient


def fetch_market_data_from_go(symbol: str) -> Dict[str, Any]:
    """
    从Go引擎的HTTP API获取当前市场数据。
    这里需要您根据实际API端点调整。
    """
    # 示例：假设Go引擎在 /api/v1/market/book 提供订单簿
    import requests
    try:
        resp = requests.get("http://localhost:8080/api/v1/market/book", params={"symbol": symbol}, timeout=0.5)
        if resp.status_code == 200:
            data = resp.json()
            # 解析为MarketState，这里需要您根据实际数据结构调整
            bid = data.get("bids", [[0,0]])[0][0]
            ask = data.get("asks", [[0,0]])[0][0]
            mid = (bid + ask) / 2
            return {
                "bid": bid,
                "ask": ask,
                "bid_size": data.get("bids", [[0,0]])[0][1],
                "ask_size": data.get("asks", [[0,0]])[0][1],
                "last_price": data.get("last_price", mid),
                "mid_price": mid,
                "spread": ask - bid,
                "timestamp": time.time()
            }
    except Exception as e:
        print(f"[Error] Failed to fetch market data: {e}")
    # 返回一个默认的安全数据，避免策略崩溃
    return {
        "bid": 70000, "ask": 70000.5, "bid_size": 1, "ask_size": 1,
        "last_price": 70000, "mid_price": 70000.25, "spread": 0.5,
        "timestamp": time.time()
    }


def main():
    print("=== MarketMakerV1 Paper Trading Session ===")
    symbol = "BTCUSDT"
    run_minutes = 5  # 首次试运行5分钟

    # 1. 初始化客户端和策略
    client = ExecutorClient(base_url="http://localhost:8080")
    strategy = MarketMakerV1(
        executor=client,
        symbol=symbol,
        max_position=0.02,
        base_order_size=0.001,
        min_spread_ticks=2,
        toxic_threshold=0.6
    )

    # 2. 确保起始状态为无挂单
    print("[Init] Cancelling any existing orders...")
    client.cancel_all_orders(symbol)

    end_time = time.time() + run_minutes * 60
    tick_count = 0
    print(f"[Start] Running for {run_minutes} minutes. Press Ctrl+C to stop early.\n")

    try:
        while time.time() < end_time:
            tick_start = time.time()
            tick_count += 1

            # 3. 获取数据
            market_raw = fetch_market_data_from_go(symbol)
            position_info = client.get_position(symbol)  # 从Go引擎获取实时仓位

            # 4. 构建策略所需的市场状态
            # 注意：需要从您的风控模块获取 toxic_score 和 volatility，此处为示例
            market_state = MarketState(
                timestamp=market_raw["timestamp"],
                bid=market_raw["bid"],
                ask=market_raw["ask"],
                bid_size=market_raw["bid_size"],
                ask_size=market_raw["ask_size"],
                last_price=market_raw["last_price"],
                spread=market_raw["spread"],
                mid_price=market_raw["mid_price"],
                toxic_score=0.0,  # 需替换为真实值
                volatility=0.001, # 需替换为真实值
                trade_imbalance=0.0
            )

            # 5. 核心：策略处理tick
            strategy.on_market_tick(market_state, position_info)

            # 6. 简单进度输出
            if tick_count % 10 == 0:
                report = strategy.get_performance_report()
                print(f"[Tick {tick_count:4d}] Mode: {report['current_mode']:5s} | "
                      f"Pos: {strategy.current_position:+.4f} | "
                      f"Orders: {report['active_orders']} | "
                      f"Filled: {report['orders_filled']}")

            # 7. 控制循环频率 (例如 2Hz)
            time.sleep(max(0, 0.5 - (time.time() - tick_start)))

    except KeyboardInterrupt:
        print("\n\n[Interrupt] Stopped by user.")
    finally:
        # 8. 会话结束，清理所有订单
        print("\n[Cleaning up] Cancelling all orders...")
        client.cancel_all_orders(symbol)
        time.sleep(1)

        # 9. 最终报告
        print("\n" + "="*50)
        print("FINAL PERFORMANCE REPORT")
        print("="*50)
        final_report = strategy.get_performance_report()
        for key, value in final_report.items():
            print(f"  {key:20s}: {value}")
        print("="*50)


if __name__ == "__main__":
    main()
