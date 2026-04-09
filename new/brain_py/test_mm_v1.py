"""
MarketMakerV1 完整测试脚本
使用模拟Go引擎，无需真实API密钥
"""
import time
import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient
from mock_go_engine import MockGoEngine, run_mock_server
import threading


def run_test(duration_seconds: int = 60):
    """运行MM策略测试。"""
    print("=" * 60)
    print("MarketMakerV1 Strategy Test")
    print("=" * 60)
    print(f"Duration: {duration_seconds} seconds")
    print(f"Mode: Mock Trading (Simulated Go Engine)")
    print()

    # 1. 启动模拟服务器（在后台线程）
    print("[1] Starting mock Go engine...")
    import subprocess
    import signal

    # 在新窗口启动模拟服务器
    server_process = subprocess.Popen(
        ["python", "mock_go_engine.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )

    # 等待服务器启动
    time.sleep(2)

    # 2. 初始化客户端和策略
    print("[2] Initializing strategy...")
    client = ExecutorClient(base_url="http://localhost:8080", timeout=1.0)

    # 检查连接
    try:
        status = client.get_open_orders()
        print("    [OK] 连接到模拟引擎")
    except Exception as e:
        print(f"    [ERROR] 连接失败: {e}")
        server_process.terminate()
        return

    strategy = MarketMakerV1(
        executor=client,
        symbol="BTCUSDT",
        max_position=0.02,        # 最大0.02 BTC持仓
        base_order_size=0.001,    # 单笔0.001 BTC
        min_spread_ticks=2,       # 最小2个tick点差
        tick_size=0.01,           # BTC tick size
        toxic_threshold=0.6,      # 毒流阈值
        inventory_skew_factor=1.0 # 库存偏置系数
    )

    # 3. 清理初始状态
    print("[3] Cleaning initial orders...")
    client.cancel_all_orders("BTCUSDT")
    time.sleep(0.5)

    # 4. 运行测试循环
    print(f"[4] Starting test loop ({duration_seconds}秒)...")
    print()

    end_time = time.time() + duration_seconds
    tick_count = 0
    mode_changes = { "HOLD": 0, "MAKER": 0, "TAKER": 0 }
    last_mode = "HOLD"

    # 性能跟踪
    max_position = 0.0
    min_position = 0.0
    total_orders_placed = 0

    try:
        while time.time() < end_time:
            tick_start = time.time()
            tick_count += 1

            # 获取市场数据
            try:
                import requests
                resp = requests.get("http://localhost:8080/api/v1/market/book",
                                   params={"symbol": "BTCUSDT"}, timeout=0.5)
                market_data = resp.json()

                position_info = client.get_position("BTCUSDT")
            except Exception as e:
                print(f"[Tick {tick_count}] 数据获取失败: {e}")
                time.sleep(0.5)
                continue

            # 构建市场状态
            bid = market_data.get("bids", [[0, 0]])[0][0]
            ask = market_data.get("asks", [[0, 0]])[0][0]
            mid = (bid + ask) / 2
            spread = ask - bid

            market_state = MarketState(
                timestamp=time.time(),
                bid=bid,
                ask=ask,
                bid_size=market_data.get("bids", [[0, 0]])[0][1],
                ask_size=market_data.get("asks", [[0, 0]])[0][1],
                last_price=market_data.get("last_price", mid),
                spread=spread,
                mid_price=mid,
                toxic_score=0.0,  # 模拟环境下无毒性
                volatility=0.001,
                trade_imbalance=0.0
            )

            # 策略处理
            strategy.on_market_tick(market_state, position_info)

            # 检查成交（模拟环境下需要主动查询）
            try:
                filled_orders = requests.get("http://localhost:8080/api/v1/orders/filled",
                                            params={"symbol": "BTCUSDT"}, timeout=0.5)
                if filled_orders.status_code == 200:
                    for fill in filled_orders.json().get("fills", []):
                        strategy.on_fill(fill)
            except:
                pass  # 端点可能不存在，忽略

            # 跟踪模式变化
            if strategy.mode != last_mode:
                mode_changes[strategy.mode] = mode_changes.get(strategy.mode, 0) + 1
                last_mode = strategy.mode

            # 跟踪仓位极值
            pos = strategy.current_position
            max_position = max(max_position, pos)
            min_position = min(min_position, pos)

            # 输出进度
            if tick_count % 10 == 0:
                report = strategy.get_performance_report()
                print(f"[Tick {tick_count:4d}] Mode: {report['current_mode']:6s} | "
                      f"Pos: {strategy.current_position:+.4f} | "
                      f"Orders: {report['active_orders']:2d} | "
                      f"Placed: {report['orders_placed']:3d}")

            # 控制频率 (2Hz)
            elapsed = time.time() - tick_start
            sleep_time = max(0, 0.5 - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[User interrupt]")
    finally:
        # 5. 清理
        print("\n[5] Cleaning orders...")
        client.cancel_all_orders("BTCUSDT")

        # 终止模拟服务器
        server_process.terminate()
        try:
            server_process.wait(timeout=2)
        except:
            server_process.kill()

        # 6. 最终报告
        print("\n" + "=" * 60)
        print("Test Complete - Final Report")
        print("=" * 60)

        final_report = strategy.get_performance_report()

        print(f"\n【Basic Stats】")
        print(f"  Ticks processed:     {tick_count}")
        print(f"  Runtime:       {duration_seconds}秒")
        print(f"  Actual frequency:       {tick_count/duration_seconds:.1f} Hz")

        print(f"\n【Mode distribution】")
        print(f"  HOLD (HOLD):    {mode_changes.get('HOLD', 0)} switches")
        print(f"  MAKER (MAKER):   {mode_changes.get('MAKER', 0)} switches")
        print(f"  TAKER (TAKER):   {mode_changes.get('TAKER', 0)} switches")
        print(f"  Final mode:       {final_report['current_mode']}")

        print(f"\n【Position control】")
        print(f"  Final position:       {final_report['current_position']:+.6f} BTC")
        print(f"  Max position:       {max_position:+.6f} BTC")
        print(f"  Min position:       {min_position:+.6f} BTC")
        print(f"  Position range:       {max_position - min_position:.6f} BTC")

        within_limit = abs(final_report['current_position']) <= strategy.max_position
        status = "[PASS]" if within_limit else "[FAIL]"
        print(f"  Limit check:       {status} (|pos| <= {strategy.max_position})")

        print(f"\n【Order stats】")
        print(f"  Orders placed:       {final_report['orders_placed']}")
        print(f"  Orders filled:       {final_report['orders_filled']}")
        print(f"  Active orders:       {final_report['active_orders']}")

        if final_report['orders_placed'] > 0:
            fill_rate = final_report['orders_filled'] / final_report['orders_placed'] * 100
            print(f"  Fill rate:         {fill_rate:.1f}%")

        print(f"\n【Key checks】")
        checks = []

        # 检查1: Position limit
        pos_check = abs(final_report['current_position']) <= strategy.max_position
        checks.append(("Position limit", pos_check,
                      f"|{final_report['current_position']:.4f}| <= {strategy.max_position}"))

        # 检查2: 有Order activity
        active_check = final_report['orders_placed'] > 0
        checks.append(("Order activity", active_check,
                      f"placed={final_report['orders_placed']} > 0"))

        # 检查3: Mode switch正常
        mode_check = mode_changes.get('MAKER', 0) > 0
        checks.append(("Mode switch", mode_check,
                      f"MAKERentries > 0"))

        all_pass = True
        for name, passed, detail in checks:
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {status} {name}: {detail}")
            if not passed:
                all_pass = False

        print()
        if all_pass:
            print("[OK] All key checks passed - Strategy running normally")
        else:
            print("[FAIL] Some checks failed - Investigation needed")

        print("=" * 60)

        return all_pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test MarketMakerV1 Strategy")
    parser.add_argument("--duration", type=int, default=60,
                       help="Test duration in seconds (default: 60)")
    args = parser.parse_args()

    success = run_test(args.duration)
    sys.exit(0 if success else 1)
