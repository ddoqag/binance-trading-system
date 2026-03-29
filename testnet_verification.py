#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安测试网验证脚本
用于在实盘前验证交易系统的基本功能
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
        logging.FileHandler('testnet_verification.log')
    ]
)

logger = logging.getLogger('TestnetVerification')

# 加载环境变量
load_dotenv()

# 检查是否安装了 python-binance
try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceRequestException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    logger.warning("python-binance not installed, will use mock data")

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestnetVerification:
    """测试网验证类"""

    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')
        self.use_testnet = os.getenv('USE_TESTNET', 'true').lower() == 'true'
        self.symbol = os.getenv('TRADING_SYMBOL', 'BTCUSDT')
        self.client = None
        self.verification_results = []

    def print_separator(self, title):
        """打印分隔线"""
        print("\n" + "="*60)
        print(f"  {title}")
        print("="*60)

    def add_result(self, test_name, passed, message=''):
        """添加验证结果"""
        self.verification_results.append({
            'test': test_name,
            'passed': passed,
            'message': message,
            'timestamp': datetime.now()
        })
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {test_name}: {message}")

    def verify_environment(self):
        """验证环境配置"""
        self.print_separator("1. 环境配置验证")

        # 检查 API 密钥
        if not self.api_key or not self.api_secret:
            self.add_result("API 密钥配置", False, "未配置 API 密钥")
            return False
        self.add_result("API 密钥配置", True, "API 密钥已配置")

        # 检查测试网配置
        if self.use_testnet:
            self.add_result("测试网模式", True, "已启用测试网模式")
        else:
            self.add_result("测试网模式", False, "警告：当前为主网模式！")

        # 检查交易对
        self.add_result("交易对配置", True, f"交易对: {self.symbol}")

        return True

    def verify_api_connection(self):
        """验证 API 连接"""
        self.print_separator("2. API 连接验证")

        if not BINANCE_AVAILABLE:
            self.add_result("python-binance 安装", False, "未安装 python-binance")
            return False
        self.add_result("python-binance 安装", True, "已安装 python-binance")

        try:
            # 初始化客户端
            self.client = Client(
                self.api_key,
                self.api_secret,
                testnet=self.use_testnet
            )
            self.add_result("客户端初始化", True, "客户端初始化成功")

            # 测试连接
            server_time = self.client.get_server_time()
            self.add_result("服务器连接", True, f"服务器时间: {server_time['serverTime']}")

            # 获取交易所信息
            exchange_info = self.client.get_exchange_info()
            self.add_result("交易所信息", True, f"交易所版本: {exchange_info.get('serverTime', 'N/A')}")

            # 验证交易对
            symbol_info = next(
                (s for s in exchange_info['symbols'] if s['symbol'] == self.symbol),
                None
            )
            if symbol_info:
                self.add_result("交易对验证", True, f"{self.symbol} 有效，状态: {symbol_info['status']}")
            else:
                self.add_result("交易对验证", False, f"{self.symbol} 不存在")

            return True

        except BinanceAPIException as e:
            self.add_result("API 连接", False, f"API 错误: {e}")
            return False
        except Exception as e:
            self.add_result("API 连接", False, f"连接错误: {e}")
            return False

    def verify_account_info(self):
        """验证账户信息"""
        self.print_separator("3. 账户信息验证")

        if not self.client:
            self.add_result("账户信息", False, "客户端未初始化")
            return False

        try:
            # 获取账户信息
            account = self.client.get_account()
            self.add_result("账户查询", True, "账户查询成功")

            # 显示余额
            balances = account.get('balances', [])
            usdt_balance = next(
                (b for b in balances if b['asset'] == 'USDT'),
                None
            )
            if usdt_balance:
                free = float(usdt_balance['free'])
                locked = float(usdt_balance['locked'])
                self.add_result("USDT 余额", True, f"可用: {free:.2f}, 锁定: {locked:.2f}")
            else:
                self.add_result("USDT 余额", False, "未找到 USDT 余额")

            return True

        except BinanceAPIException as e:
            self.add_result("账户信息", False, f"API 错误: {e}")
            return False
        except Exception as e:
            self.add_result("账户信息", False, f"查询错误: {e}")
            return False

    def verify_market_data(self):
        """验证市场数据"""
        self.print_separator("4. 市场数据验证")

        if not self.client:
            self.add_result("市场数据", False, "客户端未初始化")
            return False

        try:
            # 获取最新价格
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            price = float(ticker['price'])
            self.add_result("最新价格", True, f"{self.symbol}: ${price:.2f}")

            # 获取 K 线数据
            klines = self.client.get_klines(
                symbol=self.symbol,
                interval=Client.KLINE_INTERVAL_1HOUR,
                limit=10
            )
            self.add_result("K 线数据", True, f"获取到 {len(klines)} 根 K 线")

            if klines:
                latest_kline = klines[-1]
                close_price = float(latest_kline[4])
                volume = float(latest_kline[5])
                self.add_result("最新 K 线", True, f"收盘价: ${close_price:.2f}, 成交量: {volume:.2f}")

            # 获取 24 小时行情
            ticker_24h = self.client.get_ticker(symbol=self.symbol)
            price_change = float(ticker_24h['priceChangePercent'])
            self.add_result("24 小时行情", True, f"涨跌幅: {price_change:.2f}%")

            return True

        except BinanceAPIException as e:
            self.add_result("市场数据", False, f"API 错误: {e}")
            return False
        except Exception as e:
            self.add_result("市场数据", False, f"获取错误: {e}")
            return False

    def verify_order_management(self):
        """验证订单管理（测试网专用）"""
        self.print_separator("5. 订单管理验证")

        if not self.client:
            self.add_result("订单管理", False, "客户端未初始化")
            return False

        if not self.use_testnet:
            self.add_result("订单管理", False, "跳过：非测试网模式，不进行下单测试")
            return True

        try:
            # 获取当前价格
            ticker = self.client.get_symbol_ticker(symbol=self.symbol)
            current_price = float(ticker['price'])

            # 使用非常小的数量和远离市价的价格测试
            # 这样订单不会成交，可以安全测试
            test_quantity = 0.0001  # 极小数量
            test_price = round(current_price * 0.98, 2)  # 市价 -2%，不会成交但不触发 PRICE_FILTER

            self.add_result("测试参数", True, f"测试数量: {test_quantity}, 测试价格: ${test_price:.2f}")

            # 测试创建限价买单
            order = self.client.create_order(
                symbol=self.symbol,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_LIMIT,
                timeInForce=Client.TIME_IN_FORCE_GTC,
                quantity=test_quantity,
                price=test_price
            )
            order_id = order['orderId']
            self.add_result("创建订单", True, f"订单 ID: {order_id}")

            # 查询订单
            queried_order = self.client.get_order(
                symbol=self.symbol,
                orderId=order_id
            )
            self.add_result("查询订单", True, f"订单状态: {queried_order['status']}")

            # 取消订单
            canceled_order = self.client.cancel_order(
                symbol=self.symbol,
                orderId=order_id
            )
            self.add_result("取消订单", True, f"取消状态: {canceled_order['status']}")

            # 查询未成交订单
            open_orders = self.client.get_open_orders(symbol=self.symbol)
            self.add_result("未成交订单", True, f"未成交订单数量: {len(open_orders)}")

            return True

        except BinanceAPIException as e:
            self.add_result("订单管理", False, f"API 错误: {e}")
            return False
        except Exception as e:
            self.add_result("订单管理", False, f"操作错误: {e}")
            return False

    def print_summary(self):
        """打印验证总结"""
        self.print_separator("验证总结")

        total_tests = len(self.verification_results)
        passed_tests = sum(1 for r in self.verification_results if r['passed'])
        failed_tests = total_tests - passed_tests

        print(f"\n总测试数: {total_tests}")
        print(f"通过: {passed_tests}")
        print(f"失败: {failed_tests}")
        print(f"通过率: {(passed_tests/total_tests*100):.1f}%")

        if failed_tests == 0:
            print("\n[SUCCESS] 所有测试通过！")
            print("\n下一步：")
            print("1. 阅读 REAL_TRADING_VERIFICATION_GUIDE.md")
            print("2. 使用小资金进行实盘验证")
            print("3. 密切监控交易执行")
        else:
            print("\n[WARNING] 部分测试失败，请检查配置")
            print("\n失败的测试：")
            for result in self.verification_results:
                if not result['passed']:
                    print(f"  - {result['test']}: {result['message']}")

        print("\n" + "="*60)

    def run(self):
        """运行完整的验证流程"""
        print("="*60)
        print("  币安测试网验证脚本")
        print("="*60)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"网络: {'测试网' if self.use_testnet else '主网'}")

        try:
            # 运行所有验证
            self.verify_environment()
            time.sleep(0.5)

            self.verify_api_connection()
            time.sleep(0.5)

            self.verify_account_info()
            time.sleep(0.5)

            self.verify_market_data()
            time.sleep(0.5)

            if self.use_testnet:
                self.verify_order_management()

            self.print_summary()

        except KeyboardInterrupt:
            print("\n\n用户中断验证")
        except Exception as e:
            logger.error(f"验证过程出错: {e}")
            import traceback
            traceback.print_exc()


def main():
    """主函数"""
    print("""
╔════════════════════════════════════════════════════════════╗
║                    币安测试网验证脚本                        ║
║                                                              ║
║  此脚本用于验证交易系统在币安测试网的基本功能                ║
║                                                              ║
║  验证内容：                                                  ║
║    1. 环境配置检查                                          ║
║    2. API 连接测试                                          ║
║    3. 账户信息查询                                          ║
║    4. 市场数据获取                                          ║
║    5. 订单管理测试（测试网专用）                            ║
║                                                              ║
╚════════════════════════════════════════════════════════════╝
    """)

    # 确认继续
    confirm = input("\n是否继续进行测试网验证? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("已取消")
        return 0

    verifier = TestnetVerification()
    verifier.run()

    return 0


if __name__ == '__main__':
    sys.exit(main())
