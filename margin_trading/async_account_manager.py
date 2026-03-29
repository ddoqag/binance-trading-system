#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步全仓杠杆账户管理器

基于 sammchardy python-binance 异步最佳实践实现
支持并发账户信息查询和持仓管理
"""

import asyncio
import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from binance.exceptions import BinanceAPIException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False
    class BinanceAPIException(Exception):
        pass


class RiskLevel(Enum):
    """风险等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PositionSide(Enum):
    """持仓方向枚举"""
    LONG = "LONG"
    SHORT = "SHORT"


# 默认配置常量
DEFAULT_CACHE_TTL_SECONDS = 5
DEFAULT_BASE_LEVERAGE = 3.0
DEFAULT_MAX_LEVERAGE = 5.0
DEFAULT_LIQUIDATION_WARNING_THRESHOLD = 1.3
DEFAULT_LIQUIDATION_STOP_THRESHOLD = 1.1
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_QUOTE_ASSET = "USDT"

# API 响应字段名常量
API_FIELD_TOTAL_ASSET = "totalAssetOfBtc"
API_FIELD_TOTAL_LIABILITY = "totalLiabilityOfBtc"
API_FIELD_NET_ASSET = "totalNetAssetOfBtc"
API_FIELD_TRADE_ENABLED = "tradeEnabled"
API_FIELD_TRANSFER_ENABLED = "transferEnabled"
API_FIELD_BORROW_ENABLED = "borrowEnabled"
API_FIELD_USER_ASSETS = "userAssets"
API_FIELD_ASSET = "asset"
API_FIELD_FREE = "free"
API_FIELD_NET_ASSET_ITEM = "netAsset"
API_FIELD_BORROWED = "borrowed"
API_FIELD_PRICE = "price"
API_FIELD_AMOUNT = "amount"


logger = logging.getLogger(__name__)


@dataclass
class MarginAccountInfo:
    """全仓杠杆账户信息"""
    total_asset_btc: float  # 总资产 (BTC计价)
    total_liability_btc: float  # 总负债 (BTC计价)
    net_asset_btc: float  # 净资产 (BTC计价)
    leverage_ratio: float  # 当前杠杆倍数
    margin_level: float  # 保证金水平
    trade_enabled: bool  # 是否可交易
    transfer_enabled: bool  # 是否可转账
    borrow_enabled: bool  # 是否可借贷
    assets: List[Dict[str, Any]] = field(default_factory=list)  # 各资产详情
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarginPosition:
    """杠杆持仓详情"""
    symbol: str  # 交易对
    base_asset: str  # 基础资产 (如 BTC)
    quote_asset: str  # 计价资产 (如 USDT)
    base_amount: float  # 基础资产数量
    quote_amount: float  # 计价资产数量
    borrowed_base: float  # 已借基础资产
    borrowed_quote: float  # 已借计价资产
    net_position: float  # 净持仓 (正=多头, 负=空头)


class AsyncMarginAccountManager:
    """
    异步全仓杠杆账户管理器

    基于 python-binance AsyncClient 的封装，提供：
    - 账户信息查询（支持缓存）
    - 保证金水平计算
    - 可借贷额度查询
    - 强平风险检测
    - 并发请求支持
    """

    # 强平风险阈值
    MARGIN_LEVEL_LOW = 2.0  # 低风险阈值
    MARGIN_LEVEL_WARNING = 1.5  # 警告阈值
    MARGIN_LEVEL_DANGER = 1.3  # 危险阈值
    LIQUIDATION_LEVEL = 1.1  # 强平阈值

    def __init__(
        self,
        async_client: Optional[Any] = None,
        config: Optional[Dict] = None
    ):
        """
        初始化异步账户管理器

        Args:
            async_client: Binance AsyncClient 实例
            config: 配置字典
        """
        self.async_client = async_client
        cfg = config or {}
        self.symbol = cfg.get('symbol', DEFAULT_SYMBOL)
        self.base_leverage = cfg.get('base_leverage', DEFAULT_BASE_LEVERAGE)
        self.max_leverage = cfg.get('max_leverage', DEFAULT_MAX_LEVERAGE)
        self.liquidation_warning_threshold = cfg.get(
            'liquidation_warning_threshold', DEFAULT_LIQUIDATION_WARNING_THRESHOLD
        )
        self.liquidation_stop_threshold = cfg.get(
            'liquidation_stop_threshold', DEFAULT_LIQUIDATION_STOP_THRESHOLD
        )
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = DEFAULT_CACHE_TTL_SECONDS

    @property
    def client(self):
        """获取异步客户端"""
        return self.async_client

    async def get_account_info(self, use_cache: bool = True) -> MarginAccountInfo:
        """
        查询全仓杠杆账户信息

        Args:
            use_cache: 是否使用缓存数据

        Returns:
            MarginAccountInfo 包含账户信息
        """
        if use_cache and self._is_cache_valid():
            cached = self._cache.get("account_info")
            if isinstance(cached, MarginAccountInfo):
                return cached

        account = await self.async_client.get_margin_account()

        total_asset = float(account.get(API_FIELD_TOTAL_ASSET, 0))
        total_liability = float(account.get(API_FIELD_TOTAL_LIABILITY, 0))
        net_asset = float(account.get(API_FIELD_NET_ASSET, 0))

        leverage_ratio = self._calculate_leverage_ratio(total_asset, net_asset)
        margin_level = self._calculate_margin_level(total_asset, total_liability)

        info = MarginAccountInfo(
            total_asset_btc=total_asset,
            total_liability_btc=total_liability,
            net_asset_btc=net_asset,
            leverage_ratio=leverage_ratio,
            margin_level=margin_level,
            trade_enabled=account.get(API_FIELD_TRADE_ENABLED, False),
            transfer_enabled=account.get(API_FIELD_TRANSFER_ENABLED, False),
            borrow_enabled=account.get(API_FIELD_BORROW_ENABLED, False),
            assets=account.get(API_FIELD_USER_ASSETS, []),
            updated_at=datetime.now()
        )

        self._cache["account_info"] = info
        self._cache_time = datetime.now()
        return info

    async def get_margin_level(self, use_cache: bool = True) -> float:
        """获取保证金水平"""
        account_info = await self.get_account_info(use_cache=use_cache)
        return account_info.margin_level

    async def get_available_margin(self, asset: str = DEFAULT_QUOTE_ASSET, use_cache: bool = True) -> float:
        """获取资产的可用保证金"""
        account_info = await self.get_account_info(use_cache=use_cache)
        for a in account_info.assets:
            if a.get(API_FIELD_ASSET) == asset:
                return float(a.get(API_FIELD_FREE, 0))
        return 0.0

    async def get_position_value(self, asset: str, use_cache: bool = True) -> float:
        """获取特定资产的持仓价值"""
        account_info = await self.get_account_info(use_cache=use_cache)
        user_assets = account_info.assets

        for item in user_assets:
            if item.get(API_FIELD_ASSET) == asset:
                net_asset = float(item.get(API_FIELD_NET_ASSET_ITEM, 0))
                if net_asset == 0:
                    return 0.0

                ticker_symbol = f"{asset}{DEFAULT_QUOTE_ASSET}"
                try:
                    ticker = await self.async_client.get_symbol_ticker(
                        symbol=ticker_symbol
                    )
                except BinanceAPIException:
                    logger.warning(
                        f"Failed to get ticker for {ticker_symbol}, "
                        f"returning 0.0 for position value"
                    )
                    return 0.0

                price = float(ticker.get(API_FIELD_PRICE, 0))
                return net_asset * price

        return 0.0

    async def get_borrowable_amount(self, asset: str, use_cache: bool = True) -> float:
        """获取资产的可借贷额度"""
        cache_key = f"borrowable_{asset}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if isinstance(cached, (int, float)):
                return float(cached)

        try:
            result = await self.async_client.get_max_margin_loan(
                asset=asset, symbol=self.symbol
            )
            amount = float(result.get(API_FIELD_AMOUNT, 0))
            self._cache[cache_key] = amount
            return amount
        except BinanceAPIException as e:
            logger.error(f"Failed to get borrowable amount for {asset}: {e}")
            return 0.0

    async def is_liquidation_risk(self, use_cache: bool = True) -> bool:
        """检查是否接近强平"""
        margin_level = await self.get_margin_level(use_cache=use_cache)

        if margin_level == float('inf'):
            return False

        return margin_level <= self.liquidation_warning_threshold

    async def get_liquidation_price(
        self, symbol: str, side: str, use_cache: bool = True
    ) -> Optional[float]:
        """估算强平价格"""
        if side not in (PositionSide.LONG.value, PositionSide.SHORT.value):
            logger.warning(
                f"Invalid side: {side}. Use '{PositionSide.LONG.value}' or '{PositionSide.SHORT.value}'"
            )
            return None

        account_info = await self.get_account_info(use_cache=use_cache)
        margin_level = account_info.margin_level

        if margin_level == float('inf'):
            return None

        if margin_level <= 1:
            return None

        try:
            ticker = await self.async_client.get_symbol_ticker(symbol=symbol)
        except BinanceAPIException:
            logger.warning(
                f"Failed to get ticker for {symbol}, "
                f"cannot estimate liquidation price"
            )
            return None

        current_price = float(ticker.get(API_FIELD_PRICE, 0))
        if current_price == 0:
            return None

        if side == PositionSide.LONG.value:
            liq_price = current_price * (margin_level - 1) / margin_level
        else:  # SHORT
            liq_price = current_price * margin_level / (margin_level - 1)

        return liq_price

    async def get_position_details(self, symbol: str, use_cache: bool = True) -> Optional[MarginPosition]:
        """获取特定交易对的持仓详情"""
        account_info = await self.get_account_info(use_cache=use_cache)
        assets = account_info.assets

        base_asset, quote_asset = self._parse_symbol(symbol)

        base_info = None
        quote_info = None

        for a in assets:
            if a.get(API_FIELD_ASSET) == base_asset:
                base_info = a
            elif a.get(API_FIELD_ASSET) == quote_asset:
                quote_info = a

        if not base_info or not quote_info:
            return None

        base_amount = float(base_info.get(API_FIELD_NET_ASSET_ITEM, 0))
        quote_amount = float(quote_info.get(API_FIELD_NET_ASSET_ITEM, 0))

        if base_amount > 0:
            net_position = base_amount
        elif base_amount < 0:
            net_position = base_amount
        else:
            return None

        return MarginPosition(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            base_amount=abs(base_amount),
            quote_amount=abs(quote_amount),
            borrowed_base=float(base_info.get(API_FIELD_BORROWED, 0)),
            borrowed_quote=float(quote_info.get(API_FIELD_BORROWED, 0)),
            net_position=net_position
        )

    async def calculate_liquidation_risk(self, use_cache: bool = True) -> Dict[str, Any]:
        """计算强平风险等级"""
        info = await self.get_account_info(use_cache=use_cache)
        margin_level = info.margin_level

        if margin_level >= self.MARGIN_LEVEL_LOW:
            risk_level = RiskLevel.LOW.value
        elif margin_level >= self.MARGIN_LEVEL_WARNING:
            risk_level = RiskLevel.MEDIUM.value
        elif margin_level >= self.MARGIN_LEVEL_DANGER:
            risk_level = RiskLevel.HIGH.value
        else:
            risk_level = RiskLevel.CRITICAL.value

        if margin_level > self.LIQUIDATION_LEVEL:
            distance = (margin_level - self.LIQUIDATION_LEVEL) / self.LIQUIDATION_LEVEL
        else:
            distance = 0.0

        is_at_risk = margin_level < self.MARGIN_LEVEL_WARNING

        return {
            "is_at_risk": is_at_risk,
            "risk_level": risk_level,
            "margin_level": margin_level,
            "distance_to_liquidation": distance,
        }

    # ==================== 并发操作 ====================

    async def get_multiple_assets_info(
        self, assets: List[str]
    ) -> Dict[str, Dict[str, float]]:
        """并发获取多个资产的信息"""
        # 并发获取账户信息和所有价格
        account_info_task = self.get_account_info(use_cache=False)
        ticker_tasks = [
            self.async_client.get_symbol_ticker(symbol=f"{asset}{DEFAULT_QUOTE_ASSET}")
            for asset in assets if asset != DEFAULT_QUOTE_ASSET
        ]

        results = await asyncio.gather(
            account_info_task,
            *ticker_tasks,
            return_exceptions=True
        )

        account_info = results[0]
        ticker_results = results[1:]

        # 构建价格映射
        prices = {}
        for asset, ticker in zip(
            [a for a in assets if a != DEFAULT_QUOTE_ASSET],
            ticker_results
        ):
            if not isinstance(ticker, Exception):
                prices[asset] = float(ticker.get(API_FIELD_PRICE, 0))

        # 提取资产信息
        assets_info = {}
        user_assets = account_info.assets if isinstance(account_info, MarginAccountInfo) else []

        for a in user_assets:
            asset_name = a.get(API_FIELD_ASSET)
            if asset_name in assets:
                free = float(a.get(API_FIELD_FREE, 0))
                net = float(a.get(API_FIELD_NET_ASSET_ITEM, 0))
                borrowed = float(a.get(API_FIELD_BORROWED, 0))

                assets_info[asset_name] = {
                    'free': free,
                    'net': net,
                    'borrowed': borrowed,
                    'price': prices.get(asset_name, 1.0 if asset_name == DEFAULT_QUOTE_ASSET else 0.0)
                }

        return assets_info

    async def get_all_borrowable_amounts(self, assets: List[str]) -> Dict[str, float]:
        """并发获取多个资产的可借贷额度"""
        tasks = [self.get_borrowable_amount(asset, use_cache=False) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        borrowable = {}
        for asset, result in zip(assets, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to get borrowable for {asset}: {result}")
                borrowable[asset] = 0.0
            else:
                borrowable[asset] = result

        return borrowable

    # ==================== 工具方法 ====================

    def _is_cache_valid(self) -> bool:
        if self._cache_time is None:
            return False
        elapsed = (datetime.now() - self._cache_time).total_seconds()
        return elapsed < self._cache_ttl_seconds

    def _calculate_leverage_ratio(self, total_asset: float, net_asset: float) -> float:
        if net_asset <= 0:
            return 0.0
        return total_asset / net_asset

    def _calculate_margin_level(self, total_asset: float, total_liability: float) -> float:
        if total_liability <= 0:
            return float("inf")
        total_equity = total_asset - total_liability
        if total_equity <= 0:
            return 0.0
        return total_asset / total_liability

    def _parse_symbol(self, symbol: str) -> tuple:
        if symbol.endswith("USDT"):
            return symbol[:-4], "USDT"
        elif symbol.endswith("BTC"):
            return symbol[:-3], "BTC"
        elif symbol.endswith("ETH"):
            return symbol[:-3], "ETH"
        else:
            raise ValueError(f"Unsupported symbol format: {symbol}")

    async def refresh_cache(self) -> None:
        """刷新缓存"""
        self._cache.clear()
        self._cache_time = None
        # 重新加载账户信息
        await self.get_account_info(use_cache=False)
        logger.debug("Cache refreshed")


# ==================== 便捷函数 ====================

async def create_async_margin_account_manager(
    async_client: Any,
    config: Optional[Dict] = None
) -> AsyncMarginAccountManager:
    """
    工厂函数：创建异步账户管理器

    Args:
        async_client: Binance AsyncClient 实例
        config: 配置字典

    Returns:
        AsyncMarginAccountManager 实例
    """
    manager = AsyncMarginAccountManager(async_client, config)
    # 预加载账户信息
    await manager.get_account_info(use_cache=False)
    return manager
