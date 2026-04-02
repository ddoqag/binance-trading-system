#!/usr/bin/env python3
"""
紧急平仓脚本 - 用于关闭风险空头仓位

当前账户状态（危险）：
- 保证金水平: 1.51 (危险，接近1.2爆仓线)
- 空头仓位: ~0.000435 BTC
- 可用余额: ~$10 USDT

使用方法:
    python emergency_close_position.py [--dry-run]

参数:
    --dry-run: 仅模拟，不实际执行交易
"""
import asyncio
import sys
import os
import argparse
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from trading.async_spot_margin_executor import AsyncSpotMarginExecutor


class EmergencyPositionCloser:
    """紧急平仓器"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.executor: Optional[AsyncSpotMarginExecutor] = None
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.executor = AsyncSpotMarginExecutor(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=False,  # 主网！真实资金！
            initial_margin=10000.0,
            max_leverage=3.0
        )
        await self.executor.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.executor:
            await self.executor.close()

    async def get_account_status(self) -> Dict:
        """获取账户状态"""
        print("\n" + "=" * 70)
        print("  账户状态检查")
        print("=" * 70)

        account = await self.executor.get_account_info()

        margin_level = float(account.get('marginLevel', 0))
        total_asset_btc = float(account.get('totalAssetOfBtc', 0))
        total_liability_btc = float(account.get('totalLiabilityOfBtc', 0))
        total_net_asset_btc = float(account.get('totalNetAssetOfBtc', 0))

        # 获取 BTC 价格
        try:
            ticker = await self.executor.client.get_symbol_ticker(symbol='BTCUSDT')
            btc_price = float(ticker.get('price', 83000))
        except:
            btc_price = 83000  # 默认值

        print(f"\n保证金水平: {margin_level:.2f}")
        print(f"总资产 (BTC): {total_asset_btc:.8f}")
        print(f"总负债 (BTC): {total_liability_btc:.8f}")
        print(f"净资产 (BTC): {total_net_asset_btc:.8f}")
        print(f"BTC 价格: ${btc_price:,.2f}")

        # 风险评级
        print("\n风险评级:", end=" ")
        if margin_level < 1.2:
            print("🔴 危险！即将爆仓！")
        elif margin_level < 1.5:
            print("🔴 高风险！接近危险线！")
        elif margin_level < 2.0:
            print("🟡 警告！低于安全线！")
        else:
            print("🟢 安全")

        # 列出所有资产
        print("\n持仓详情:")
        print(f"{'资产':<10} {'可用':>15} {'锁定':>15} {'借入':>15} {'净值':>15}")
        print("-" * 70)

        has_borrowed = False
        for asset_info in account.get('userAssets', []):
            asset = asset_info['asset']
            free = float(asset_info.get('free', 0))
            locked = float(asset_info.get('locked', 0))
            borrowed = float(asset_info.get('borrowed', 0))
            net_asset = float(asset_info.get('netAsset', 0))

            if free != 0 or locked != 0 or borrowed != 0:
                print(f"{asset:<10} {free:>15.8f} {locked:>15.8f} {borrowed:>15.8f} {net_asset:>15.8f}")
                if borrowed > 0:
                    has_borrowed = True

        return {
            'margin_level': margin_level,
            'btc_price': btc_price,
            'total_liability_btc': total_liability_btc,
            'has_borrowed': has_borrowed
        }

    async def get_btc_position(self) -> Optional[Dict]:
        """获取 BTC 持仓详情"""
        print("\n" + "=" * 70)
        print("  BTC 持仓检查")
        print("=" * 70)

        position = await self.executor.get_position('BTCUSDT')

        if position is None:
            print("未检测到 BTC 持仓")
            return None

        print(f"\n交易对: {position.symbol}")
        print(f"持仓方向: {'多头' if position.position > 0 else '空头'}")
        print(f"持仓数量: {abs(position.position):.8f} BTC")
        print(f"借入数量: {position.borrowed:.8f} BTC")
        print(f"可用数量: {position.free:.8f} BTC")
        print(f"锁定数量: {position.locked:.8f} BTC")

        return {
            'symbol': position.symbol,
            'side': 'LONG' if position.position > 0 else 'SHORT',
            'size': abs(position.position),
            'borrowed': position.borrowed,
            'free': position.free
        }

    async def close_short_position(self, position: Dict, btc_price: float):
        """关闭空头仓位"""
        print("\n" + "=" * 70)
        print("  执行平仓操作")
        print("=" * 70)

        borrowed_btc = position['borrowed']
        available_btc = position['free']

        print(f"\n需要归还: {borrowed_btc:.8f} BTC")
        print(f"当前可用: {available_btc:.8f} BTC")

        # 计算需要买入的 BTC 数量
        btc_to_buy = max(0, borrowed_btc - available_btc)

        if btc_to_buy > 0:
            usdt_needed = btc_to_buy * btc_price * 1.005  # 加0.5%缓冲
            print(f"需要买入: {btc_to_buy:.8f} BTC")
            print(f"预计需要: ~${usdt_needed:.2f} USDT")

            # 检查 USDT 余额
            usdt_balance = await self.executor.get_balance('USDT')
            print(f"USDT 可用: {usdt_balance.free:.2f}")

            if usdt_balance.free < usdt_needed * 0.95:  # 允许5%误差
                print(f"\n⚠️ 警告: USDT 余额不足！")
                print(f"需要: ${usdt_needed:.2f}, 可用: ${usdt_balance.free:.2f}")
                print("\n选项:")
                print("1. 转入更多 USDT 到全仓杠杆账户")
                print("2. 减少部分负债后重试")
                return False

            # 执行市价买入
            if self.dry_run:
                print(f"\n[模拟模式] 将执行市价买入 {btc_to_buy:.8f} BTC")
                print("           实际上不会执行任何交易")
            else:
                print(f"\n正在执行市价买入 {btc_to_buy:.8f} BTC...")
                try:
                    result = await self.executor.place_market_order(
                        symbol='BTCUSDT',
                        side='BUY',
                        quantity=btc_to_buy
                    )
                    print(f"✅ 买入成功!")
                    print(f"   订单ID: {result.order_id}")
                    print(f"   成交数量: {result.executed_qty:.8f}")
                    print(f"   成交均价: ${result.avg_price:.2f}")
                    print(f"   总花费: ${result.total_quote_qty:.2f}")

                    # 等待订单确认
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"❌ 买入失败: {e}")
                    return False
        else:
            print(f"\n已有足够 BTC，无需买入")

        # 归还借入的 BTC
        if self.dry_run:
            print(f"\n[模拟模式] 将归还 {borrowed_btc:.8f} BTC")
        else:
            print(f"\n正在归还 {borrowed_btc:.8f} BTC...")
            try:
                tran_id = await self.executor.repay('BTC', borrowed_btc)
                print(f"✅ 归还成功! 交易ID: {tran_id}")

                # 等待确认
                await asyncio.sleep(1)

            except Exception as e:
                print(f"❌ 归还失败: {e}")
                return False

        return True

    async def verify_position_closed(self) -> bool:
        """验证仓位是否已关闭"""
        print("\n" + "=" * 70)
        print("  验证平仓结果")
        print("=" * 70)

        position = await self.executor.get_position('BTCUSDT')

        if position is None or abs(position.position) < 1e-10:
            print("✅ 仓位已成功关闭!")
            return True
        else:
            print(f"⚠️ 仓位仍未完全关闭:")
            print(f"   持仓: {position.position:.8f} BTC")
            print(f"   借入: {position.borrowed:.8f} BTC")
            return False

    async def run(self):
        """运行紧急平仓流程"""
        print("\n" + "=" * 70)
        if self.dry_run:
            print("  紧急平仓脚本 [模拟模式]")
        else:
            print("  紧急平仓脚本 [实盘模式 - 将执行真实交易!]")
        print("=" * 70)

        # 1. 获取账户状态
        account_status = await self.get_account_status()

        if not account_status['has_borrowed']:
            print("\n✅ 没有发现借入资产，无需平仓")
            return

        # 2. 获取 BTC 持仓
        position = await self.get_btc_position()

        if position is None:
            print("\n没有发现 BTC 持仓，但仍需检查借入资产...")
            # 检查 BTC 借入
            btc_balance = await self.executor.get_balance('BTC')
            if btc_balance.borrowed > 0:
                position = {
                    'symbol': 'BTCUSDT',
                    'side': 'SHORT',
                    'size': btc_balance.borrowed,
                    'borrowed': btc_balance.borrowed,
                    'free': btc_balance.free
                }
            else:
                print("没有 BTC 借入，无需操作")
                return

        if position['side'] != 'SHORT':
            print(f"\n⚠️ 检测到 {position['side']} 仓位，不是空头")
            print("此脚本仅用于关闭空头仓位")
            return

        # 3. 确认操作
        print("\n" + "=" * 70)
        print("  操作确认")
        print("=" * 70)
        print(f"\n将要执行以下操作:")
        print(f"1. 买入 {position['borrowed'] - position['free']:.8f} BTC (如有需要)")
        print(f"2. 归还 {position['borrowed']:.8f} BTC 借款")
        print(f"3. 关闭空头仓位")

        if self.dry_run:
            print("\n[模拟模式] 不执行实际交易")
            return

        # 自动执行平仓（无手动确认）
        print("\n⚠️  自动执行平仓操作...")

        # 4. 执行平仓
        success = await self.close_short_position(position, account_status['btc_price'])

        if not success:
            print("\n❌ 平仓失败")
            return

        # 5. 验证结果
        await asyncio.sleep(2)  # 等待状态更新
        closed = await self.verify_position_closed()

        if closed:
            print("\n" + "=" * 70)
            print("  ✅ 紧急平仓成功!")
            print("=" * 70)

            # 显示最终状态
            final_status = await self.get_account_status()
            print(f"\n最终保证金水平: {final_status['margin_level']:.2f}")
        else:
            print("\n" + "=" * 70)
            print("  ⚠️  平仓可能未完成，请手动检查")
            print("=" * 70)


async def main():
    parser = argparse.ArgumentParser(description='紧急平仓脚本')
    parser.add_argument('--dry-run', action='store_true',
                        help='模拟模式，不执行实际交易')

    args = parser.parse_args()

    try:
        async with EmergencyPositionCloser(dry_run=args.dry_run) as closer:
            await closer.run()
    except KeyboardInterrupt:
        print("\n\n操作被用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(main())
