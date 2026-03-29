"""
Web API - 简单的 REST API
可选功能，需要 FastAPI
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger('WebAPI')


@dataclass
class APIResponse:
    """API 响应格式"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None


class TradingAPI:
    """
    交易系统 API
    提供 REST API 接口（需要 FastAPI/Flask 才能实际运行）
    """

    def __init__(self):
        logger.info("TradingAPI initialized")

    def get_market_data(self, symbol: str, interval: str = '1h',
                       limit: int = 100) -> APIResponse:
        """
        获取市场数据

        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 数据条数

        Returns:
            APIResponse
        """
        try:
            from data.loader import DataLoader
            loader = DataLoader()
            df = loader.load_ohlcv(symbol, interval)

            if df.empty:
                return APIResponse(
                    success=False,
                    error=f"No data found for {symbol}_{interval}"
                )

            return APIResponse(
                success=True,
                data=df.tail(limit).reset_index().to_dict('records')
            )
        except Exception as e:
            logger.error(f"Error getting market data: {e}")
            return APIResponse(success=False, error=str(e))

    def get_indicators(self, symbol: str, interval: str = '1h',
                      limit: int = 100) -> APIResponse:
        """
        获取技术指标

        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 数据条数

        Returns:
            APIResponse
        """
        try:
            from data.loader import DataLoader
            from models.features import FeatureEngineer

            loader = DataLoader()
            df = loader.load_ohlcv(symbol, interval)

            if df.empty:
                return APIResponse(
                    success=False,
                    error=f"No data found for {symbol}_{interval}"
                )

            fe = FeatureEngineer()
            df_with_features = fe.add_technical_indicators(df)

            return APIResponse(
                success=True,
                data=df_with_features.tail(limit).reset_index().to_dict('records')
            )
        except Exception as e:
            logger.error(f"Error getting indicators: {e}")
            return APIResponse(success=False, error=str(e))

    def run_strategy(self, strategy_name: str,
                    symbol: str, interval: str = '1h') -> APIResponse:
        """
        运行策略

        Args:
            strategy_name: 策略名称
            symbol: 交易对
            interval: 时间周期

        Returns:
            APIResponse
        """
        try:
            from data.loader import DataLoader

            loader = DataLoader()
            df = loader.load_ohlcv(symbol, interval)

            if df.empty:
                return APIResponse(
                    success=False,
                    error=f"No data found for {symbol}_{interval}"
                )

            # Load strategy based on name
            strategy = None
            if strategy_name.lower() == 'rsi':
                from strategy.rsi_strategy import RSIStrategy
                strategy = RSIStrategy()
            elif strategy_name.lower() == 'dual_ma':
                from strategy.dual_ma import DualMAStrategy
                strategy = DualMAStrategy()
            else:
                return APIResponse(
                    success=False,
                    error=f"Unknown strategy: {strategy_name}"
                )

            signals = strategy.generate_signals(df)

            return APIResponse(
                success=True,
                data={
                    'strategy': strategy_name,
                    'symbol': symbol,
                    'buy_signals': int((signals['signal'] == 1).sum()),
                    'sell_signals': int((signals['signal'] == -1).sum()),
                    'latest_signal': int(signals['signal'].iloc[-1]) if len(signals) > 0 else 0
                }
            )
        except Exception as e:
            logger.error(f"Error running strategy: {e}")
            return APIResponse(success=False, error=str(e))

    def get_system_status(self) -> APIResponse:
        """
        获取系统状态

        Returns:
            APIResponse
        """
        try:
            from data.loader import DataLoader
            loader = DataLoader()
            available_data = loader.list_available_data()

            return APIResponse(
                success=True,
                data={
                    'status': 'online',
                    'timestamp': datetime.now().isoformat(),
                    'available_data': available_data
                }
            )
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return APIResponse(success=False, error=str(e))


# For FastAPI (if installed)
try:
    from fastapi import FastAPI

    app = FastAPI(title="Binance Trading System API")
    api = TradingAPI()

    @app.get("/")
    async def root():
        return {"message": "Binance Trading System API"}

    @app.get("/api/status")
    async def get_status():
        return api.get_system_status()

    @app.get("/api/market/{symbol}")
    async def get_market(symbol: str, interval: str = '1h', limit: int = 100):
        return api.get_market_data(symbol, interval, limit)

    @app.get("/api/indicators/{symbol}")
    async def get_indicators(symbol: str, interval: str = '1h', limit: int = 100):
        return api.get_indicators(symbol, interval, limit)

    @app.post("/api/strategy/{strategy_name}")
    async def run_strategy(strategy_name: str, symbol: str, interval: str = '1h'):
        return api.run_strategy(strategy_name, symbol, interval)

    logger.info("FastAPI app created")

except ImportError:
    logger.info("FastAPI not installed, API class available but no HTTP server")
