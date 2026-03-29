#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Margin Trading Test Fixtures

共享测试固件和模拟对象
"""

import pytest
from unittest.mock import MagicMock
from typing import Dict, Any


@pytest.fixture
def mock_binance_client():
    """模拟 Binance API 客户端"""
    client = MagicMock()

    # Mock margin account data
    client.get_margin_account.return_value = {
        'totalAssetOfBtc': '1.5',
        'totalLiabilityOfBtc': '0.5',
        'totalNetAssetOfBtc': '1.0',
        'marginLevel': '3.0',
        'assets': [
            {
                'asset': 'BTC',
                'free': '0.5',
                'locked': '0.1',
                'borrowed': '0.0',
                'interest': '0.0',
                'netAsset': '0.6'
            },
            {
                'asset': 'USDT',
                'free': '10000.0',
                'locked': '2000.0',
                'borrowed': '0.0',
                'interest': '0.0',
                'netAsset': '12000.0'
            }
        ]
    }

    # Mock ticker price
    client.get_symbol_ticker.return_value = {
        'symbol': 'BTCUSDT',
        'price': '50000.0'
    }

    # Mock order placement
    client.create_margin_order.return_value = {
        'orderId': 123456789,
        'symbol': 'BTCUSDT',
        'side': 'BUY',
        'type': 'MARKET',
        'status': 'FILLED',
        'executedQty': '0.1',
        'cummulativeQuoteQty': '5000.0',
        'transactTime': 1234567890000
    }

    return client


@pytest.fixture
def sample_account_config():
    """样本账户配置"""
    return {
        'symbol': 'BTCUSDT',
        'base_leverage': 3.0,
        'max_leverage': 5.0,
        'min_leverage': 1.0,
        'initial_balance': 10000.0,
        'fee_rate': 0.001,
        'slippage_rate': 0.0005
    }


@pytest.fixture
def sample_risk_config():
    """样本风控配置"""
    return {
        'max_position_size': 0.8,
        'max_single_position': 0.2,
        'daily_loss_limit': -0.05,
        'max_leverage': 5.0,
        'liquidation_warning_threshold': 1.3,
        'liquidation_stop_threshold': 1.1,
        'volatility_factor_enabled': True,
        'regime_factor_enabled': True
    }


@pytest.fixture
def sample_ai_context_response():
    """样本 AI 上下文响应"""
    return {
        'direction': 'LONG',
        'confidence': 0.75,
        'timestamp': 1234567890,
        'models_agreed': 6,
        'models_total': 8,
        'model_breakdown': {
            'Doubao': '看涨',
            'Yuanbao': '看涨',
            'Antafu': '中性',
            'ChatGPT': '看涨',
            'Gemini': '看跌',
            'Copilot': '看涨',
            'Grok': '看涨',
            'Poe': '中性'
        }
    }
