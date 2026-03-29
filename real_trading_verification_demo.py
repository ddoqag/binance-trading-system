#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘验证演示脚本
安全地验证交易系统功能（模拟模式）
"""

import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('real_trading_verification.log')
    ]
)

logger = logging.getLogger('RealTradingVerification')

# 加载环境变量
load_dotenv()

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from trading.leverage_executor import LeverageTradingExecutor
    from trading.order import OrderSide, OrderType, OrderStatus
    TRADING_MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Trading modules not available: {e}")
    TRADING_MODULES_AVAILABLE = False


class RealTradingVerificationDemo:
    """实盘验证演示类"""

    def __init__(self):
        self.symbol = os.getenv('DEFAULT_SYMBOL', 'BTCUSDT')
        self.initial_capital = float(os.getenv('INITIAL_CAPITAL', '10000'))
        self.max_leverage = float(os.getenv('MAX_LEVERAGE', '10.0'))
        self.paper_trading = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        self.executor = None
        self.verification_steps = []

    def print_separator(self, title):
        """打印分隔线"""
        print("\n" + "="*70)
        print(f"  {title}")
        print("="*70)

    def add_step(self, step_name, passed, details=''):
        """添加验证步骤"""
        self.verification_steps.append({
            'step': step_name,
            'passed': passed,
            'details': details,
            'timestamp': datetime.now()
        })
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {step_name}")
        if details:
            print(f"   {details}")

    def initialize_executor(self):
        """初始化交易执行器"""
        self.print_separator("步骤 1: 初始化交易执行器")

        if not TRADING_MODULES_AVAILABLE:
            self.add_step("模块导入", False, "交易模块不可用")
            return False

        try:
            self.executor = LeverageTradingExecutor(
                initial_margin=self.initial_capital,
                max_leverage=self.max_leverage,
                maintenance_margin_rate=0.005,
                is_paper_trading=self.paper_trading,
                commission_rate=0.001,
                slippage=0.0005
            )
            self.add_step("执行器初始化", True, f"初始资金: ${self.initial_capital:.2f}")

            balance = self.executor.get_balance_info()
            self.add_step("余额查询", True, f"可用: ${balance['available_balance']:.2f}, "
                                                f"总余额: ${balance['total_balance']:.2f}")

            return True

        except Exception as e:
            self.add_step("执行器初始化", False, f"错误: {e}")
            return False

    def simulate_market_data(self):
        """模拟市场数据"""
        self.print_separator("步骤 2: 模拟市场数据")

        # 模拟价格序列
        base_price = 45000.0
        prices = [
            base_price * 0.98,  # 下跌 2%
            base_price * 0.99,  # 下跌 1%
            base_price,         # 基准价
            base_price * 1.01,  # 上涨 1%
            base_price * 1.02,  # 上涨 2%
            base_price * 1.03,  # 上涨 3%
        ]

        self.add_step("价格模拟", True, f"生成 {len(prices)} 个价格点")
        self.add_step("价格范围", True, f"${min(prices):.2f} - ${max(prices):.2f}")

        return prices

    def test_long_position(self, prices):
        """测试做多"""
        self.print_separator("步骤 3: 测试做多（10x 杠杆）")

        if not self.executor:
            self.add_step("做多测试", False, "执行器未初始化")
            return False

        try:
            entry_price = prices[0]
            leverage = 10.0

            # 计算可开仓数量
            quantity = self.executor.calculate_position_size(
                self.symbol,
                OrderSide.BUY,
                entry_price,
                leverage
            )
            self.add_step("开仓数量计算", True, f"可开 {quantity:.6f} {self.symbol}")

            if quantity <= 0:
                self.add_step("开多仓", False, "可开仓数量为 0")
                return False

            # 开多仓
            order = self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                leverage=leverage,
                current_price=entry_price
            )

            if order.status == OrderStatus.FILLED:
                self.add_step("开多仓", True, f"成交 {order.filled_quantity:.6f} @ ${order.avg_price:.2f}")
            else:
                self.add_step("开多仓", False, f"订单状态: {order.status}")
                return False

            # 检查持仓
            pos = self.executor.get_position_info(self.symbol)
            if pos:
                self.add_step("持仓查询", True, f"持仓: {pos.position:.6f}, "
                                                f"开仓价: ${pos.entry_price:.2f}, "
                                                f"强平价: ${pos.liquidation_price:.2f}")

            # 价格上涨时的盈亏
            price_high = prices[-1]
            pnl = self.executor.calculate_unrealized_pnl(self.symbol, price_high)
            self.add_step("上涨盈亏", True, f"价格 ${price_high:.2f} 时, 盈亏: ${pnl:.2f}")

            # 平仓
            close_order = self.executor.close_position(self.symbol, price_high, leverage)
            if close_order and close_order.status == OrderStatus.FILLED:
                self.add_step("平多仓", True, f"平仓 {close_order.filled_quantity:.6f} @ ${close_order.avg_price:.2f}")

            # 检查余额
            balance = self.executor.get_balance_info()
            self.add_step("余额更新", True, f"总余额: ${balance['total_balance']:.2f}, "
                                                f"盈亏: ${balance['total_pnl']:.2f}")

            return True

        except Exception as e:
            self.add_step("做多测试", False, f"错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_short_position(self, prices):
        """测试做空"""
        self.print_separator("步骤 4: 测试做空（5x 杠杆）")

        if not self.executor:
            self.add_step("做空测试", False, "执行器未初始化")
            return False

        try:
            entry_price = prices[-1]
            leverage = 5.0

            # 计算可开仓数量
            quantity = self.executor.calculate_position_size(
                self.symbol,
                OrderSide.SELL,
                entry_price,
                leverage
            )
            self.add_step("开仓数量计算", True, f"可开 {quantity:.6f} {self.symbol}")

            if quantity <= 0:
                self.add_step("开空仓", False, "可开仓数量为 0")
                return False

            # 开空仓
            order = self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=quantity,
                leverage=leverage,
                current_price=entry_price
            )

            if order.status == OrderStatus.FILLED:
                self.add_step("开空仓", True, f"成交 {order.filled_quantity:.6f} @ ${order.avg_price:.2f}")
            else:
                self.add_step("开空仓", False, f"订单状态: {order.status}")
                return False

            # 检查持仓
            pos = self.executor.get_position_info(self.symbol)
            if pos:
                self.add_step("持仓查询", True, f"持仓: {pos.position:.6f} (空头), "
                                                f"开仓价: ${pos.entry_price:.2f}")

            # 价格下跌时的盈亏
            price_low = prices[0]
            pnl = self.executor.calculate_unrealized_pnl(self.symbol, price_low)
            self.add_step("下跌盈亏", True, f"价格 ${price_low:.2f} 时, 盈亏: ${pnl:.2f}")

            # 平空仓
            close_order = self.executor.close_position(self.symbol, price_low, leverage)
            if close_order and close_order.status == OrderStatus.FILLED:
                self.add_step("平空仓", True, f"平仓 {close_order.filled_quantity:.6f} @ ${close_order.avg_price:.2f}")

            # 检查余额
            balance = self.executor.get_balance_info()
            self.add_step("余额更新", True, f"总余额: ${balance['total_balance']:.2f}, "
                                                f"盈亏: ${balance['total_pnl']:.2f}")

            return True

        except Exception as e:
            self.add_step("做空测试", False, f"错误: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_order_history(self):
        """测试订单历史"""
        self.print_separator("步骤 5: 测试订单历史")

        if not self.executor:
            self.add_step("订单历史", False, "执行器未初始化")
            return False

        try:
            order_history = self.executor.get_order_history()
            self.add_step("历史查询", True, f"共 {len(order_history)} 条订单记录")

            if order_history:
                self.add_step("订单详情", True, "最近 5 笔订单:")
                for i, order in enumerate(order_history[-5:], 1):
                    side = "做多" if order.side == OrderSide.BUY else "做空"
                    status = "成交" if order.status == OrderStatus.FILLED else "未成交"
                    print(f"     {i}. {side} {order.filled_quantity:.4f} @ ${order.avg_price or 0:.2f} ({status})")

            return True

        except Exception as e:
            self.add_step("订单历史", False, f"错误: {e}")
            return False

    def print_summary(self):
        """打印验证总结"""
        self.print_separator("实盘验证总结")

        total_steps = len(self.verification_steps)
        passed_steps = sum(1 for s in self.verification_steps if s['passed'])
        failed_steps = total_steps - passed_steps

        print(f"\n总步骤数: {total_steps}")
        print(f"通过: {passed_steps}")
        print(f"失败: {failed_steps}")
        print(f"通过率: {(passed_steps/total_steps*100):.1f}%")

        if self.executor:
            balance = self.executor.get_balance_info()
            print(f"\n最终余额: ${balance['total_balance']:.2f}")
            print(f"总盈亏: ${balance['total_pnl']:.2f}")
            print(f"收益率: {(balance['total_pnl']/self.initial_capital*100):.2f}%")

        if failed_steps == 0:
            print("\n✅ 所有验证步骤通过！")
            print("\n下一步：")
            print("1. 阅读 REAL_TRADING_VERIFICATION_GUIDE.md")
            print("2. 使用 testnet_verification.py 在测试网验证")
            print("3. 使用小资金进行实盘验证")
            print("4. 密切监控交易执行")
        else:
            print("\n⚠️  部分验证失败，请检查系统配置")

        print("\n" + "="*70)

    def run(self):
        """运行完整的验证流程"""
        print("""
╔═══════════════════════════════════════════════════════════════╗
║                    实盘验证演示脚本                              ║
║                                                               ║
║  此脚本安全地验证交易系统功能，使用模拟模式                    ║
║  不会执行真实的交易                                            ║
║                                                               ║
║  验证内容：                                                   ║
║    1. 初始化交易执行器                                        ║
║    2. 模拟市场数据                                            ║
║    3. 测试做多（10x 杠杆）                                    ║
║    4. 测试做空（5x 杠杆）                                     ║
║    5. 验证订单历史                                            ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """)

        print(f"\n配置信息:")
        print(f"  交易对: {self.symbol}")
        print(f"  初始资金: ${self.initial_capital:.2f}")
        print(f"  最大杠杆: {self.max_leverage}x")
        print(f"  模拟模式: {self.paper_trading}")

        # 确认继续
        confirm = input("\n是否继续进行实盘验证演示? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("已取消")
            return 0

        try:
            # 运行所有验证步骤
            if not self.initialize_executor():
                print("\n初始化失败，终止验证")
                return 1

            prices = self.simulate_market_data()

            if not self.test_long_position(prices):
                print("\n做多测试失败")

            if not self.test_short_position(prices):
                print("\n做空测试失败")

            if not self.test_order_history():
                print("\n订单历史测试失败")

            self.print_summary()

        except KeyboardInterrupt:
            print("\n\n用户中断验证")
        except Exception as e:
            logger.error(f"验证过程出错: {e}")
            import traceback
            traceback.print_exc()

        return 0


def main():
    """主函数"""
    demo = RealTradingVerificationDemo()
    return demo.run()


if __name__ == '__main__':
    sys.exit(main())
