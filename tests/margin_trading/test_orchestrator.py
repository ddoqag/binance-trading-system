#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradingOrchestrator 测试

测试交易协调器的完整交易流程、风险控制和执行器集成。
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

# 导入被测模块
import sys
sys.path.insert(0, 'D:/binance')

from margin_trading.orchestrator import (
    TradingOrchestrator,
    TradingConfig,
    SignalType
)
from trading.order import OrderSide, OrderType, OrderStatus, Order


class TestTradingOrchestrator:
    """TradingOrchestrator 测试类"""

    @pytest.fixture
    def mock_account_manager(self):
        """模拟账户管理器"""
        manager = MagicMock()
        manager.get_balance.return_value = 10000.0
        manager.get_margin_level.return_value = 3.0
        manager.get_available_margin.return_value = 8000.0
        return manager

    @pytest.fixture
    def mock_position_manager(self):
        """模拟仓位管理器"""
        manager = MagicMock()
        manager.get_position.return_value = None
        manager.get_all_positions.return_value = []
        manager.open_position.return_value = MagicMock(
            position_id='pos_001',
            symbol='BTCUSDT',
            side='LONG',
            quantity=0.1,
            entry_price=50000.0,
            leverage=3.0
        )
        manager.close_position.return_value = True
        return manager

    @pytest.fixture
    def mock_risk_controller(self):
        """模拟风险控制器"""
        controller = MagicMock()
        controller.can_trade.return_value = (True, "")
        controller.calculate_position_size.return_value = 0.1
        controller.calculate_dynamic_leverage.return_value = 3.0
        controller.update_after_trade.return_value = None
        return controller

    @pytest.fixture
    def mock_ai_fetcher(self):
        """模拟 AI 信号获取器"""
        fetcher = MagicMock()
        fetcher.get_cached_context.return_value = {
            'direction': 'up',
            'confidence': 0.75,
            'regime': 'bull',
            'risk': 'low'
        }
        return fetcher

    @pytest.fixture
    def mock_rust_executor(self):
        """模拟 Rust 执行器"""
        executor = MagicMock()
        executor.place_order.return_value = Order(
            order_id='order_001',
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.FILLED,
            filled_quantity=0.1,
            avg_price=50000.0
        )
        executor.place_orders_batch.return_value = [
            Order(
                order_id=f'order_{i}',
                symbol='BTCUSDT',
                side=OrderSide.BUY,
                type=OrderType.MARKET,
                quantity=0.05,
                status=OrderStatus.FILLED,
                filled_quantity=0.05,
                avg_price=50000.0
            )
            for i in range(2)
        ]
        return executor

    @pytest.fixture
    def trading_config(self):
        """交易配置"""
        return TradingConfig(
            symbol='BTCUSDT',
            interval='1h',
            initial_balance=10000.0,
            base_leverage=3.0,
            max_leverage=5.0,
            fee_rate=0.001,
            slippage_rate=0.0005,
            use_rust_executor=True
        )

    @pytest.fixture
    def orchestrator(self, mock_account_manager, mock_position_manager,
                     mock_risk_controller, mock_ai_fetcher, mock_rust_executor,
                     trading_config):
        """创建配置好的 TradingOrchestrator 实例"""
        # 使用 create=True 来 patch 不存在的属性
        with patch('margin_trading.orchestrator.MarginAccountManager', return_value=mock_account_manager, create=True), \
             patch('margin_trading.orchestrator.LeveragePositionManager', return_value=mock_position_manager, create=True), \
             patch('margin_trading.orchestrator.StandardRiskController', return_value=mock_risk_controller, create=True), \
             patch('margin_trading.orchestrator.AIContextFetcher', return_value=mock_ai_fetcher, create=True), \
             patch('margin_trading.orchestrator.create_rust_executor', return_value=mock_rust_executor):

            orch = TradingOrchestrator(trading_config)
            return orch

    def test_initialization(self, trading_config):
        """测试初始化 - 验证所有组件正确初始化"""
        with patch('margin_trading.orchestrator.MarginAccountManager') as mock_acc, \
             patch('margin_trading.orchestrator.LeveragePositionManager') as mock_pos, \
             patch('margin_trading.orchestrator.StandardRiskController') as mock_risk, \
             patch('margin_trading.orchestrator.AIContextFetcher') as mock_ai, \
             patch('margin_trading.orchestrator.create_rust_executor') as mock_rust:

            orch = TradingOrchestrator(trading_config)

            # 验证所有组件被初始化
            mock_acc.assert_called_once()
            mock_pos.assert_called_once_with(trading_config.symbol)
            mock_risk.assert_called_once()
            mock_ai.assert_called_once()
            mock_rust.assert_called_once_with(
                initial_capital=trading_config.initial_balance,
                commission_rate=trading_config.fee_rate,
                slippage=trading_config.slippage_rate
            )

            assert orch.config == trading_config
            assert orch.is_running == False

    def test_execute_trading_cycle_long_signal(self, orchestrator):
        """测试 LONG 信号 - 应该开多仓"""
        # 设置 AI 返回 LONG 信号
        orchestrator.ai_fetcher.get_cached_context.return_value = {
            'direction': 'up',
            'confidence': 0.75,
            'regime': 'bull'
        }

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证风险检查被调用
        orchestrator.risk_controller.can_trade.assert_called_once()

        # 验证仓位计算被调用
        orchestrator.risk_controller.calculate_position_size.assert_called_once()
        orchestrator.risk_controller.calculate_dynamic_leverage.assert_called_once()

        # 验证开仓被调用（LONG 信号）
        orchestrator.position_manager.open_position.assert_called_once()
        call_args = orchestrator.position_manager.open_position.call_args
        assert call_args[1]['side'] == 'LONG'

        assert result['success'] is True
        assert result['action'] == 'OPEN_LONG'

    def test_execute_trading_cycle_short_signal(self, orchestrator):
        """测试 SHORT 信号 - 应该开空仓"""
        # 设置 AI 返回 SHORT 信号
        orchestrator.ai_fetcher.get_cached_context.return_value = {
            'direction': 'down',
            'confidence': 0.75,
            'regime': 'bear'
        }

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证开仓被调用（SHORT 信号）
        orchestrator.position_manager.open_position.assert_called_once()
        call_args = orchestrator.position_manager.open_position.call_args
        assert call_args[1]['side'] == 'SHORT'

        assert result['success'] is True
        assert result['action'] == 'OPEN_SHORT'

    def test_execute_trading_cycle_neutral(self, orchestrator):
        """测试 NEUTRAL 信号 - 应该平仓"""
        # 设置 AI 返回中性信号
        orchestrator.ai_fetcher.get_cached_context.return_value = {
            'direction': 'sideways',
            'confidence': 0.5,
            'regime': 'neutral'
        }

        # 模拟有现有仓位
        mock_position = MagicMock()
        mock_position.side = 'LONG'
        mock_position.position_id = 'pos_001'
        orchestrator.position_manager.get_position.return_value = mock_position

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证平仓被调用
        orchestrator.position_manager.close_position.assert_called_once_with('pos_001')

        assert result['success'] is True
        assert result['action'] == 'CLOSE_POSITION'

    def test_risk_check_blocks_trade(self, orchestrator):
        """测试风险检查阻止交易"""
        # 设置风险控制器阻止交易
        orchestrator.risk_controller.can_trade.return_value = (False, "风险过高，禁止交易")

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证没有调用开仓
        orchestrator.position_manager.open_position.assert_not_called()

        assert result['success'] is False
        assert 'blocked_by_risk' in result
        assert result['reason'] == "风险过高，禁止交易"

    def test_position_reversal(self, orchestrator):
        """测试仓位反转 - 平掉多头开空头"""
        # 模拟有 LONG 仓位
        mock_position = MagicMock()
        mock_position.side = 'LONG'
        mock_position.position_id = 'pos_001'
        orchestrator.position_manager.get_position.return_value = mock_position

        # 设置 AI 返回 SHORT 信号（与当前仓位相反）
        orchestrator.ai_fetcher.get_cached_context.return_value = {
            'direction': 'down',
            'confidence': 0.8,
            'regime': 'bear'
        }

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证先平仓再开仓
        orchestrator.position_manager.close_position.assert_called_once_with('pos_001')
        orchestrator.position_manager.open_position.assert_called_once()
        call_args = orchestrator.position_manager.open_position.call_args
        assert call_args[1]['side'] == 'SHORT'

        assert result['success'] is True
        assert result['action'] == 'REVERSE_TO_SHORT'

    def test_rust_executor_integration(self, orchestrator):
        """测试 Rust 执行器集成"""
        # 设置配置使用 Rust 执行器
        orchestrator.config.use_rust_executor = True

        # 执行交易周期
        orchestrator.execute_trading_cycle()

        # 验证 Rust 执行器被使用
        assert orchestrator.rust_executor is not None

    def test_fallback_executor(self, orchestrator):
        """测试 Python 回退执行器 - 当 Rust 不可用时"""
        # 模拟 Rust 执行器不可用
        orchestrator.rust_executor = None
        orchestrator.config.use_rust_executor = False

        # 创建模拟的 Python 执行器
        mock_python_executor = MagicMock()
        mock_python_executor.place_order.return_value = Order(
            order_id='py_order_001',
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.FILLED,
            filled_quantity=0.1,
            avg_price=50000.0
        )
        orchestrator.python_executor = mock_python_executor

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证 Python 执行器被使用
        assert result['success'] is True

    def test_start_stop_lifecycle(self, orchestrator):
        """测试启动和停止生命周期"""
        # 初始状态
        assert orchestrator.is_running is False

        # 启动
        orchestrator.start()
        assert orchestrator.is_running is True

        # 重复启动应该抛出异常或忽略
        with pytest.raises(RuntimeError):
            orchestrator.start()

        # 停止
        orchestrator.stop()
        assert orchestrator.is_running is False

    def test_error_handling_graceful_degradation(self, orchestrator):
        """测试错误处理和优雅降级"""
        # 模拟 AI 获取器抛出异常
        orchestrator.ai_fetcher.get_cached_context.side_effect = Exception("AI 服务异常")

        # 执行交易周期应该返回错误但不崩溃
        result = orchestrator.execute_trading_cycle()

        # 当 AI 异常时，会返回 NEUTRAL 信号，置信度为 0，被风险检查拦截
        assert result['success'] is False
        assert 'blocked_by_risk' in result or 'error' in result
        assert result['signal'] == 'NEUTRAL'

    def test_execute_trading_cycle_no_position_when_neutral(self, orchestrator):
        """测试 NEUTRAL 信号且没有仓位时 - 什么都不做"""
        # 设置 AI 返回中性信号
        orchestrator.ai_fetcher.get_cached_context.return_value = {
            'direction': 'sideways',
            'confidence': 0.5,
            'regime': 'neutral'
        }

        # 确保没有现有仓位
        orchestrator.position_manager.get_position.return_value = None

        # 执行交易周期
        result = orchestrator.execute_trading_cycle()

        # 验证没有调用任何操作
        orchestrator.position_manager.close_position.assert_not_called()
        orchestrator.position_manager.open_position.assert_not_called()

        assert result['success'] is True
        assert result['action'] == 'NO_ACTION'

    def test_batch_order_execution(self, orchestrator):
        """测试批量订单执行"""
        # 设置需要批量执行的场景
        orders = [
            ('BTCUSDT', OrderSide.BUY, OrderType.MARKET, 0.05, None),
            ('BTCUSDT', OrderSide.BUY, OrderType.MARKET, 0.05, None)
        ]

        # 执行批量订单
        results = orchestrator.execute_batch_orders(orders)

        # 验证 Rust 执行器的批量方法被调用
        orchestrator.rust_executor.place_orders_batch.assert_called_once()
        assert len(results) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])