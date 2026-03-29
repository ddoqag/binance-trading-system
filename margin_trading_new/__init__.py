#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Margin Trading Package - Phase 1 Implementation

全仓杠杆交易系统的 Phase 1 实现模块，包含以下核心组件：

- MarginAccountManager: 全仓杠杆账户管理
- AIHybridSignalGenerator: 混合模式 AI 信号生成
- LeveragePositionManager: 全仓仓位管理
- StandardRiskController: 标准风控
- TradingOrchestrator: 交易编排器

Usage:
    from margin_trading.account_manager import MarginAccountManager
    from margin_trading.ai_signal import AIHybridSignalGenerator
    from margin_trading.position_manager import LeveragePositionManager
    from margin_trading.risk_controller import StandardRiskController
    from margin_trading.orchestrator import TradingOrchestrator
"""

__version__ = "0.1.0"
__author__ = "Trading System"

# Re-export main classes for convenience
try:
    from .account_manager import MarginAccountManager
except ImportError:
    MarginAccountManager = None

try:
    from .ai_signal import AIHybridSignalGenerator
except ImportError:
    AIHybridSignalGenerator = None

try:
    from .position_manager import LeveragePositionManager
except ImportError:
    LeveragePositionManager = None

try:
    from .risk_controller import StandardRiskController, LeverageRiskConfig, RiskStatus
except ImportError:
    StandardRiskController = None
    LeverageRiskConfig = None
    RiskStatus = None

try:
    from .orchestrator import TradingOrchestrator
except ImportError:
    TradingOrchestrator = None

__all__ = [
    "MarginAccountManager",
    "AIHybridSignalGenerator",
    "LeveragePositionManager",
    "StandardRiskController",
    "LeverageRiskConfig",
    "RiskStatus",
    "TradingOrchestrator",
]
