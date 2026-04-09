"""
MarketMakerV1 纸交易/实盘交易脚本
连接真实Go引擎，带完整风控监控
"""
import time
import sys
import signal
from typing import Dict, Any, Optional
from datetime import datetime
from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient


class RiskMonitor:
    """简单风控监控器。"""

    def __init__(self, max_daily_loss_pct: float = 2.0, max_drawdown_pct: float = 5.0):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.initial_capital: Optional[float] = None
        self.peak_capital = 0.0
        self.daily_pnl = 0.0
        self.kill_switch_triggered = False

    def update(self, current_capital: float, position: float, position_value: float):
        """更新风控状态。"""
        if self.initial_capital is None:
            self.initial_capital = current_capital
            self.peak_capital = current_capital

        self.peak_capital = max(self.peak_capital, current_capital)

        # 计算回撤
        drawdown = (self.peak_capital - current_capital) / self.peak_capital * 100

        # 检查熔断条件
        if drawdown > self.max_drawdown_pct:
            self.kill_switch_triggered = True
            return False, f"MAX DRAWDOWN: {drawdown:.2f}% > {self.max_drawdown_pct}%"

        return True, "OK"

    def get_status(self) -> Dict[str, Any]:
        return {
            "kill_switch": self.kill_switch_triggered,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_loss_limit_pct": self.max_daily_loss_pct
        }


def fetch_market_data_from_go(symbol: str, base_url: str = "http://localhost:8080") -> Optional[Dict[str, Any]]:
    """从Go引擎获取市场数据。"""
    import requests
    try:
        resp = requests.get(f"{base_url}/api/v1/market/book",
                           params={"symbol": symbol}, timeout=1.0)
        if resp.status_code == 200:
            data = resp.json()
            bid = float(data.get("bids", [[0,0]])[0][0])
            ask = float(data.get("asks", [[0,0]])[0][0])
            mid = (bid + ask) / 2
            spread = ask - bid
            return {
                "bid": bid, "ask": ask,
                "bid_size": float(data.get("bids", [[0,0]])[0][1]),
                "ask_size": float(data.get("asks", [[0,0]])[0][1]),
                "last_price": float(data.get("last_price", mid)),
                "mid_price": mid, "spread": spread,
                "timestamp": time.time()
            }
    except Exception as e:
        print(f"[ERROR] Failed to fetch market data: {e}")
    return None


def get_toxic_score_from_go(symbol: str, base_url: str = "http://localhost:8080") -> float:
    """从Go引擎获取毒性分数（如果可用）。"""
    import requests
    try:
        # 尝试从风控接口获取
        resp = requests.get(f"{base_url}/api/v1/risk/stats", timeout=0.5)
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("toxic_score", 0.0))
    except:
        pass
    return 0.0


def main():
    print("="*60)
    print("MarketMakerV1 Paper Trading")
    print("="*60)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 配置
    SYMBOL = "BTCUSDT"
    RUN_MINUTES = 30  # 默认运行30分钟
    BASE_URL = "http://localhost:8080"

    # 风控参数
    risk_monitor = RiskMonitor(
        max_daily_loss_pct=2.0,
        max_drawdown_pct=5.0
    )

    # 初始化
    print("[1] Initializing...")
    client = ExecutorClient(base_url=BASE_URL, timeout=2.0)

    # 测试连接
    try:
        test_resp = client.get_position(SYMBOL)
        print(f"    [OK] Connected to Go engine at {BASE_URL}")
        print(f"    Position: {test_resp.get('position', 0)} BTC")
    except Exception as e:
        print(f"    [ERROR] Cannot connect to Go engine: {e}")
        print("    Make sure Go engine is running on port 8080")
        sys.exit(1)

    # 初始化策略
    strategy = MarketMakerV1(
        executor=client,
        symbol=SYMBOL,
        max_position=0.02,           # 最大0.02 BTC
        base_order_size=0.001,       # 单笔0.001 BTC
        min_spread_ticks=2,
        tick_size=0.01,
        toxic_threshold=0.6,
        inventory_skew_factor=2.0    # 加强库存偏置
    )

    # 清理初始状态
    print("[2] Cleaning existing orders...")
    client.cancel_all_orders(SYMBOL)
    time.sleep(0.5)

    # 信号处理
    running = True
    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[Signal] Shutdown requested...")

    signal.signal(signal.SIGINT, signal_handler)

    # 主循环
    print(f"[3] Starting main loop ({RUN_MINUTES} minutes)...")
    print("    Press Ctrl+C to stop early\n")

    end_time = time.time() + RUN_MINUTES * 60
    tick_count = 0
    error_count = 0
    processed_fill_ids = set()

    try:
        while running and time.time() < end_time:
            tick_start = time.time()
            tick_count += 1

            # 检查风控熔断
            if risk_monitor.kill_switch_triggered:
                print("[KILL SWITCH] Risk limit reached! Stopping...")
                break

            # 获取市场数据
            market_raw = fetch_market_data_from_go(SYMBOL, BASE_URL)
            if market_raw is None:
                error_count += 1
                if error_count > 5:
                    print("[ERROR] Too many data fetch failures, stopping...")
                    break
                time.sleep(1)
                continue

            error_count = 0  # 重置错误计数

            # 获取仓位和毒性分数
            position_info = client.get_position(SYMBOL)
            toxic_score = get_toxic_score_from_go(SYMBOL, BASE_URL)

            # 构建市场状态
            market_state = MarketState(
                timestamp=market_raw["timestamp"],
                bid=market_raw["bid"],
                ask=market_raw["ask"],
                bid_size=market_raw["bid_size"],
                ask_size=market_raw["ask_size"],
                last_price=market_raw["last_price"],
                spread=market_raw["spread"],
                mid_price=market_raw["mid_price"],
                toxic_score=toxic_score,
                volatility=0.001,  # 可以从Go引擎获取
                trade_imbalance=0.0
            )

            # 策略处理
            strategy.on_market_tick(market_state, position_info)

            # 查询并处理成交（Go引擎应该有成交回调或查询接口）
            try:
                import requests
                fills_resp = requests.get(f"{BASE_URL}/api/v1/orders/filled",
                                         params={"symbol": SYMBOL}, timeout=0.5)
                if fills_resp.status_code == 200:
                    for fill in fills_resp.json().get("fills", []):
                        fill_id = fill.get("order_id", "")
                        if fill_id and fill_id not in processed_fill_ids:
                            strategy.on_fill(fill)
                            processed_fill_ids.add(fill_id)
            except:
                pass  # 接口可能不存在

            # 进度输出（每10个tick）
            if tick_count % 10 == 0:
                report = strategy.get_performance_report()
                pos = strategy.current_position
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Tick:{tick_count:4d} | "
                      f"Mode:{report['current_mode']:6s} | "
                      f"Pos:{pos:+.4f} | "
                      f"Orders:{report['active_orders']:2d} | "
                      f"Filled:{report['orders_filled']:3d}")

            # 风控检查
            current_pos = strategy.current_position
            pos_value = current_pos * market_raw["mid_price"]
            # 简化的风控检查（实际需要账户余额信息）

            # 控制频率 (2Hz)
            elapsed = time.time() - tick_start
            sleep_time = max(0, 0.5 - elapsed)
            time.sleep(sleep_time)

    except Exception as e:
        print(f"\n[ERROR] Exception in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理
        print("\n[Cleanup] Cancelling all orders...")
        client.cancel_all_orders(SYMBOL)
        time.sleep(1)

        # 最终报告
        print("\n" + "="*60)
        print("FINAL PERFORMANCE REPORT")
        print("="*60)

        final_report = strategy.get_performance_report()
        print(f"\nRuntime Metrics:")
        print(f"  Total Ticks:        {tick_count}")
        print(f"  Runtime:            {RUN_MINUTES} minutes")
        print(f"  Errors:             {error_count}")

        print(f"\nStrategy State:")
        print(f"  Final Mode:         {final_report['current_mode']}")
        print(f"  Current Position:   {final_report['current_position']:.6f} BTC")
        print(f"  Active Orders:      {final_report['active_orders']}")

        print(f"\nTrading Statistics:")
        print(f"  Orders Placed:      {final_report['orders_placed']}")
        print(f"  Orders Filled:      {final_report['orders_filled']}")
        print(f"  Total Fill Value:   ${final_report.get('total_fill_value', 0):.2f}")
        print(f"  Total Fees:         ${final_report.get('total_fees', 0):.4f}")

        if final_report['orders_placed'] > 0:
            fill_rate = final_report['orders_filled'] / final_report['orders_placed'] * 100
            print(f"  Fill Rate:          {fill_rate:.1f}%")

        print("\n" + "="*60)
        print(f"Session End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)


if __name__ == "__main__":
    main()
