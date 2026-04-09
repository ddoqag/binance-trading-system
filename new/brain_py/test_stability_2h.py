"""
MarketMakerV1 2小时稳定性测试
监控: 内存使用、仓位漂移、订单累积、成交一致性
"""
import time
import sys
import os
import psutil
import json
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient
import requests


def get_memory_usage():
    """获取当前进程内存使用(MB)。"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def run_stability_test(duration_minutes: int = 120):
    """运行稳定性测试。"""
    print("=" * 70)
    print(f"MarketMakerV1 Stability Test - {duration_minutes} Minutes")
    print("=" * 70)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {duration_minutes} minutes ({duration_minutes/60:.1f} hours)")
    print(f"PID: {os.getpid()}")
    print()

    # 配置
    SYMBOL = "BTCUSDT"
    BASE_URL = "http://localhost:8080"
    SAMPLE_INTERVAL = 30  # 每30秒采样一次

    # 初始化
    print("[1] Initializing...")
    client = ExecutorClient(base_url=BASE_URL, timeout=2.0)

    # 检查引擎
    try:
        resp = requests.get(f"{BASE_URL}/api/v1/status", timeout=2.0)
        if resp.status_code == 200:
            print(f"    [OK] Engine connected: {resp.json().get('status', 'unknown')}")
        else:
            print(f"    [ERROR] Engine returned {resp.status_code}")
            return False
    except Exception as e:
        print(f"    [ERROR] Cannot connect: {e}")
        return False

    # 初始化策略
    strategy = MarketMakerV1(
        executor=client,
        symbol=SYMBOL,
        max_position=0.02,
        base_order_size=0.001,
        min_spread_ticks=2,
        tick_size=0.01,
        toxic_threshold=0.6,
        inventory_skew_factor=2.0
    )

    # 清理
    print("[2] Cleaning orders...")
    client.cancel_all_orders(SYMBOL)
    time.sleep(1)

    # 监控数据
    samples = []
    memory_samples = deque(maxlen=10)  # 保存最近10个内存样本
    position_samples = deque(maxlen=100)  # 保存最近100个仓位样本

    # 初始内存基准
    baseline_memory = get_memory_usage()
    print(f"[3] Baseline memory: {baseline_memory:.1f} MB")
    print()

    # 主循环
    print("[4] Starting test loop...")
    print("    (Press Ctrl+C to stop early)")
    print()

    end_time = time.time() + duration_minutes * 60
    tick_count = 0
    sample_count = 0
    processed_fill_ids = set()
    last_report_time = time.time()

    # 异常计数
    error_count = 0
    consecutive_errors = 0

    try:
        while time.time() < end_time:
            tick_start = time.time()
            tick_count += 1

            # 获取市场数据
            try:
                resp = requests.get(f"{BASE_URL}/api/v1/market/book",
                                   params={"symbol": SYMBOL}, timeout=1.0)
                data = resp.json()
                bid = float(data['bids'][0][0])
                ask = float(data['asks'][0][0])
                mid = (bid + ask) / 2

                position_info = client.get_position(SYMBOL)

                # 构建市场状态
                market = MarketState(
                    timestamp=time.time(),
                    bid=bid, ask=ask,
                    bid_size=float(data['bids'][0][1]),
                    ask_size=float(data['asks'][0][1]),
                    last_price=float(data.get('last_price', mid)),
                    spread=ask-bid,
                    mid_price=mid,
                    toxic_score=0.0,
                    volatility=0.001,
                    trade_imbalance=0.0
                )

                # 策略处理
                strategy.on_market_tick(market, position_info)

                # 检查成交
                try:
                    fills_resp = requests.get(f"{BASE_URL}/api/v1/orders/filled",
                                             params={"symbol": SYMBOL}, timeout=0.5)
                    for fill in fills_resp.json().get('fills', []):
                        fill_id = fill.get('order_id', "")
                        if fill_id and fill_id not in processed_fill_ids:
                            strategy.on_fill(fill)
                            processed_fill_ids.add(fill_id)
                except:
                    pass

                consecutive_errors = 0  # 重置错误计数

            except Exception as e:
                error_count += 1
                consecutive_errors += 1
                if consecutive_errors > 5:
                    print(f"\n[ERROR] Too many consecutive errors ({consecutive_errors}), stopping...")
                    break
                time.sleep(1)
                continue

            # 采样 (每30秒)
            if tick_count % (SAMPLE_INTERVAL * 2) == 0:  # 2Hz -> 每60 ticks = 30秒
                sample_count += 1
                current_memory = get_memory_usage()
                memory_samples.append(current_memory)
                position_samples.append(strategy.current_position)

                sample = {
                    'timestamp': datetime.now().isoformat(),
                    'elapsed_minutes': (time.time() - (end_time - duration_minutes * 60)) / 60,
                    'tick_count': tick_count,
                    'memory_mb': current_memory,
                    'memory_delta_mb': current_memory - baseline_memory,
                    'position': strategy.current_position,
                    'mode': strategy.mode,
                    'active_orders': len(strategy.active_orders),
                    'orders_placed': strategy.metrics['orders_placed'],
                    'orders_filled': strategy.metrics['orders_filled'],
                    'price': mid
                }
                samples.append(sample)

            # 进度报告 (每5分钟)
            if time.time() - last_report_time > 300:
                last_report_time = time.time()
                elapsed = (time.time() - (end_time - duration_minutes * 60)) / 60
                remaining = duration_minutes - elapsed

                report = strategy.get_performance_report()
                mem_current = get_memory_usage()
                mem_delta = mem_current - baseline_memory

                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Elapsed: {elapsed:.0f}min | "
                      f"Remaining: {remaining:.0f}min | "
                      f"Ticks: {tick_count} | "
                      f"Pos: {strategy.current_position:+.4f} | "
                      f"Mem: +{mem_delta:.1f}MB | "
                      f"Fills: {report['orders_filled']}")

            # 控制频率 (2Hz)
            elapsed = time.time() - tick_start
            sleep_time = max(0, 0.5 - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\n[User interrupt]")
    finally:
        # 清理
        print("\n[Cleanup] Cancelling orders...")
        client.cancel_all_orders(SYMBOL)

        # 生成报告
        print("\n" + "=" * 70)
        print("STABILITY TEST REPORT")
        print("=" * 70)

        actual_duration = (time.time() - (end_time - duration_minutes * 60)) / 60
        print(f"\nTest Duration:")
        print(f"  Planned: {duration_minutes} minutes")
        print(f"  Actual:  {actual_duration:.1f} minutes ({actual_duration/duration_minutes*100:.0f}%)")

        print(f"\nTick Statistics:")
        print(f"  Total Ticks: {tick_count}")
        print(f"  Average Frequency: {tick_count / (actual_duration * 60):.1f} Hz")
        print(f"  Samples Taken: {sample_count}")
        print(f"  Errors: {error_count}")

        # 内存分析
        if memory_samples:
            final_memory = get_memory_usage()
            memory_delta = final_memory - baseline_memory
            memory_growth_per_hour = (memory_delta / actual_duration) * 60 if actual_duration > 0 else 0

            print(f"\nMemory Analysis:")
            print(f"  Baseline: {baseline_memory:.1f} MB")
            print(f"  Final: {final_memory:.1f} MB")
            print(f"  Delta: {memory_delta:+.1f} MB")
            print(f"  Growth Rate: {memory_growth_per_hour:+.1f} MB/hour")

            if memory_delta > 50:
                print(f"  [WARNING] High memory growth detected!")
            else:
                print(f"  [PASS] Memory growth within acceptable range")

        # 仓位分析
        if position_samples:
            positions = list(position_samples)
            max_pos = max(positions)
            min_pos = min(positions)
            avg_pos = sum(positions) / len(positions)
            final_pos = strategy.current_position

            print(f"\nPosition Analysis:")
            print(f"  Max: {max_pos:+.6f} BTC")
            print(f"  Min: {min_pos:+.6f} BTC")
            print(f"  Average: {avg_pos:+.6f} BTC")
            print(f"  Final: {final_pos:+.6f} BTC")
            print(f"  Range: {max_pos - min_pos:.6f} BTC")

            if abs(final_pos) > 0.015:
                print(f"  [WARNING] Final position exceeds 75% of limit!")
            else:
                print(f"  [PASS] Position within safe range")

        # 订单分析
        report = strategy.get_performance_report()
        print(f"\nOrder Statistics:")
        print(f"  Placed: {report['orders_placed']}")
        print(f"  Filled: {report['orders_filled']}")
        print(f"  Active (final): {report['active_orders']}")
        print(f"  Fill Rate: {report['orders_filled'] / max(report['orders_placed'], 1) * 100:.1f}%")

        if report['active_orders'] > 10:
            print(f"  [WARNING] High active order count!")
        else:
            print(f"  [PASS] Order count normal")

        # 总体评估
        print("\n" + "=" * 70)
        print("FINAL ASSESSMENT")
        print("=" * 70)

        checks = []

        # 检查1: 运行时长
        duration_ok = actual_duration >= duration_minutes * 0.9  # 至少完成90%
        checks.append(("Duration", duration_ok, f"{actual_duration:.0f}/{duration_minutes} min"))

        # 检查2: 内存
        memory_ok = memory_delta < 50 if memory_samples else True
        checks.append(("Memory", memory_ok, f"+{memory_delta:.1f}MB < 50MB"))

        # 检查3: 仓位
        position_ok = abs(final_pos) <= 0.015
        checks.append(("Position", position_ok, f"|{final_pos:.4f}| <= 0.015"))

        # 检查4: 订单
        orders_ok = report['active_orders'] <= 10
        checks.append(("Orders", orders_ok, f"{report['active_orders']} <= 10"))

        # 检查5: 错误
        errors_ok = error_count < 10
        checks.append(("Errors", errors_ok, f"{error_count} < 10"))

        all_pass = True
        for name, passed, detail in checks:
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {status} {name}: {detail}")
            if not passed:
                all_pass = False

        print()
        if all_pass:
            print("[OK] All stability checks PASSED - Strategy is stable")
        else:
            print("[FAIL] Some checks FAILED - Review issues before production")

        print("=" * 70)

        # 保存详细数据
        report_data = {
            'start_time': datetime.now().isoformat(),
            'duration_minutes': actual_duration,
            'tick_count': tick_count,
            'samples': samples,
            'checks': {name: passed for name, passed, _ in checks},
            'all_passed': all_pass
        }

        report_file = f"stability_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        print(f"\nDetailed report saved to: {report_file}")

        return all_pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MarketMakerV1 Stability Test")
    parser.add_argument("--duration", type=int, default=120,
                       help="Test duration in minutes (default: 120 = 2 hours)")
    args = parser.parse_args()

    success = run_stability_test(args.duration)
    sys.exit(0 if success else 1)
