#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步现货杠杆接口测试

测试 AsyncSpotMarginExecutor 和 AsyncMarginAccountManager 的功能
"""

import asyncio
import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# 跳过测试的装饰器
skip_if_no_binance = pytest.mark.skipif(
    not os.getenv('BINANCE_TESTNET_API_KEY'),
    reason="需要设置 BINANCE_TESTNET_API_KEY 环境变量"
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_async_client():
    """创建模拟的 AsyncClient"""
    client = AsyncMock()

    # 模拟账户信息
    client.get_margin_account.return_value = {
        'totalAssetOfBtc': '1.5',
        'totalLiabilityOfBtc': '0.5',
        'totalNetAssetOfBtc': '1.0',
        'marginLevel': '3.0',
        'tradeEnabled': True,
        'transferEnabled': True,
        'userAssets': [
            {
                'asset': 'BTC',
                'free': '0.5',
                'locked': '0.0',
                'borrowed': '0.1',
                'netAsset': '0.4',
                'interest': '0.001'
            },
            {
                'asset': 'USDT',
                'free': '10000.0',
                'locked': '0.0',
                'borrowed': '0.0',
                'netAsset': '10000.0',
                'interest': '0.0'
            }
        ]
    }

    # 模拟订单结果
    client.create_margin_order.return_value = {
        'orderId': 123456,
        'symbol': 'BTCUSDT',
        'side': 'BUY',
        'status': 'FILLED',
        'executedQty': '0.001',
        'cummulativeQuoteQty': '45.0',
        'fills': [
            {'price': '45000.0', 'qty': '0.001'}
        ]
    }

    # 模拟最大可借
    client.get_max_margin_loan.return_value = {'amount': '1.0'}

    # 模拟借贷结果
    client.create_margin_loan.return_value = {'tranId': 789012}
    client.repay_margin_loan.return_value = {'tranId': 789013}

    # 模拟价格
    client.get_symbol_ticker.return_value = {'price': '45000.0'}

    return client


@pytest.fixture
def async_executor(mock_async_client):
    """创建异步执行器实例"""
    from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

    executor = AsyncSpotMarginExecutor(
        api_key='test_key',
        api_secret='test_secret',
        testnet=True,
        initial_margin=10000.0,
        max_leverage=3.0
    )
    executor.client = mock_async_client
    return executor


@pytest.fixture
def async_account_manager(mock_async_client):
    """创建异步账户管理器实例"""
    from margin_trading.async_account_manager import AsyncMarginAccountManager

    manager = AsyncMarginAccountManager(
        async_client=mock_async_client,
        config={'symbol': 'BTCUSDT'}
    )
    return manager


# ============================================================
# 测试 AsyncSpotMarginExecutor
# ============================================================

class TestAsyncSpotMarginExecutor:
    """测试异步现货杠杆执行器"""

    @pytest.mark.asyncio
    async def test_get_account_info(self, async_executor):
        """测试获取账户信息"""
        account = await async_executor.get_account_info(use_cache=False)

        assert account is not None
        assert 'totalAssetOfBtc' in account
        assert float(account['totalAssetOfBtc']) == 1.5

    @pytest.mark.asyncio
    async def test_get_balance(self, async_executor):
        """测试获取余额"""
        balance = await async_executor.get_balance('BTC')

        assert balance.asset == 'BTC'
        assert balance.free == 0.5
        assert balance.borrowed == 0.1
        assert balance.net_asset == 0.4

    @pytest.mark.asyncio
    async def test_get_balance_info(self, async_executor):
        """测试获取余额信息"""
        balance_info = await async_executor.get_balance_info()

        assert 'available_balance' in balance_info
        assert 'total_balance' in balance_info
        assert 'margin_level' in balance_info

    @pytest.mark.asyncio
    async def test_get_position(self, async_executor):
        """测试获取持仓"""
        position = await async_executor.get_position('BTCUSDT')

        assert position is not None
        assert position.symbol == 'BTCUSDT'
        assert position.base_asset == 'BTC'
        assert position.quote_asset == 'USDT'

    @pytest.mark.asyncio
    async def test_get_multiple_positions(self, async_executor):
        """测试并发获取多个持仓"""
        positions = await async_executor.get_multiple_positions(
            ['BTCUSDT', 'ETHUSDT']
        )

        assert 'BTCUSDT' in positions
        assert 'ETHUSDT' in positions

    @pytest.mark.asyncio
    async def test_get_multiple_balances(self, async_executor):
        """测试并发获取多个余额"""
        balances = await async_executor.get_multiple_balances(['BTC', 'USDT'])

        assert 'BTC' in balances
        assert 'USDT' in balances
        assert balances['BTC'].asset == 'BTC'

    @pytest.mark.asyncio
    async def test_place_market_order(self, async_executor):
        """测试下市价单"""
        result = await async_executor.place_market_order(
            symbol='BTCUSDT',
            side='BUY',
            quantity=0.001
        )

        assert result.order_id == 123456
        assert result.symbol == 'BTCUSDT'
        assert result.side == 'BUY'
        assert result.status == 'FILLED'

    @pytest.mark.asyncio
    async def test_get_max_borrowable(self, async_executor):
        """测试获取最大可借数量"""
        max_amount = await async_executor.get_max_borrowable('BTC')

        assert max_amount == 1.0

    @pytest.mark.asyncio
    async def test_borrow(self, async_executor):
        """测试借入资产"""
        tran_id = await async_executor.borrow('BTC', 0.5)

        assert tran_id == 789012

    @pytest.mark.asyncio
    async def test_repay(self, async_executor):
        """测试归还资产"""
        tran_id = await async_executor.repay('BTC', 0.5)

        assert tran_id == 789013


# ============================================================
# 测试 AsyncMarginAccountManager
# ============================================================

class TestAsyncMarginAccountManager:
    """测试异步账户管理器"""

    @pytest.mark.asyncio
    async def test_get_account_info(self, async_account_manager):
        """测试获取账户信息"""
        account_info = await async_account_manager.get_account_info(use_cache=False)

        assert account_info is not None
        assert account_info.total_asset_btc == 1.5
        assert account_info.total_liability_btc == 0.5
        assert account_info.net_asset_btc == 1.0
        assert account_info.margin_level == 3.0
        assert account_info.trade_enabled is True

    @pytest.mark.asyncio
    async def test_get_margin_level(self, async_account_manager):
        """测试获取保证金水平"""
        margin_level = await async_account_manager.get_margin_level(use_cache=False)

        assert margin_level == 3.0

    @pytest.mark.asyncio
    async def test_get_available_margin(self, async_account_manager):
        """测试获取可用保证金"""
        available = await async_account_manager.get_available_margin('BTC', use_cache=False)

        assert available == 0.5

    @pytest.mark.asyncio
    async def test_is_liquidation_risk(self, async_account_manager):
        """测试强平风险检测"""
        is_at_risk = await async_account_manager.is_liquidation_risk(use_cache=False)

        # 保证金水平 3.0 高于警告阈值 1.3，不应有风险
        assert is_at_risk is False

    @pytest.mark.asyncio
    async def test_calculate_liquidation_risk(self, async_account_manager):
        """测试计算强平风险"""
        risk_info = await async_account_manager.calculate_liquidation_risk(use_cache=False)

        assert 'is_at_risk' in risk_info
        assert 'risk_level' in risk_info
        assert 'margin_level' in risk_info
        assert risk_info['margin_level'] == 3.0

    @pytest.mark.asyncio
    async def test_get_position_details(self, async_account_manager):
        """测试获取持仓详情"""
        position = await async_account_manager.get_position_details('BTCUSDT', use_cache=False)

        assert position is not None
        assert position.symbol == 'BTCUSDT'
        assert position.base_asset == 'BTC'

    @pytest.mark.asyncio
    async def test_get_borrowable_amount(self, async_account_manager):
        """测试获取可借贷额度"""
        amount = await async_account_manager.get_borrowable_amount('BTC', use_cache=False)

        assert amount == 1.0


# ============================================================
# 性能对比测试
# ============================================================

class TestPerformanceComparison:
    """性能对比测试"""

    @pytest.mark.asyncio
    async def test_concurrent_vs_sequential(self, async_executor):
        """测试并发 vs 串行性能"""
        import time

        # 模拟多次查询
        symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT']

        # 串行方式（模拟）
        start = time.time()
        for symbol in symbols:
            await async_executor.get_position(symbol)
        sequential_time = time.time() - start

        # 并发方式
        start = time.time()
        await async_executor.get_multiple_positions(symbols)
        concurrent_time = time.time() - start

        # 并发应该更快或相当
        print(f"\n串行时间: {sequential_time:.3f}s")
        print(f"并发时间: {concurrent_time:.3f}s")
        if concurrent_time > 0:
            print(f"加速比: {sequential_time / concurrent_time:.2f}x")

        # 注意：在测试环境中模拟调用可能不会有显著差异
        # 在实际 API 调用中，并发优势明显


# ============================================================
# 集成测试（需要真实 API 密钥）
# ============================================================

@pytest.mark.integration
@skip_if_no_binance
class TestIntegration:
    """集成测试 - 需要真实 API 密钥"""

    @pytest.mark.asyncio
    async def test_real_account_connection(self):
        """测试真实账户连接"""
        from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

        async with AsyncSpotMarginExecutor(
            api_key=os.getenv('BINANCE_TESTNET_API_KEY'),
            api_secret=os.getenv('BINANCE_TESTNET_API_SECRET'),
            testnet=True,
            initial_margin=10000.0,
            max_leverage=3.0
        ) as executor:
            # 测试连接
            account = await executor.get_account_info()
            assert account is not None
            print(f"\n真实账户连接成功!")
            print(f"保证金水平: {account.get('marginLevel', 'N/A')}")


# ============================================================
# 主函数
# ============================================================

if __name__ == '__main__':
    # 运行测试
    pytest.main([
        __file__,
        '-v',
        '--tb=short',
        '-k', 'not integration'  # 跳过集成测试
    ])
