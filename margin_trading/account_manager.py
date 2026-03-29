#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Margin Account Manager

全仓杠杆账户管理器，用于管理币安全仓杠杆账户信息、
计算保证金水平、查询可借贷额度、估算强平价格等。
"""

import logging
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from datetime import datetime

try:
    from binance.exceptions import BinanceAPIException
except ImportError:
    class _FallbackBinanceAPIException(Exception):
        pass
    BinanceAPIException = _FallbackBinanceAPIException

from enum import Enum


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


class MarginAccountManager:
    """
    全仓杠杆账户管理器

    管理币安交叉保证金账户，提供账户信息查询、保证金水平计算、
    可借贷额度查询、强平风险检测等功能。

    Attributes:
        client: Binance API client
        config: Configuration dictionary
        symbol: Trading pair (e.g., 'BTCUSDT')
        base_leverage: Default leverage (default: 3.0)
        max_leverage: Maximum allowed leverage (default: 5.0)
        liquidation_warning_threshold: Warning threshold (default: 1.3)
        liquidation_stop_threshold: Stop trading threshold (default: 1.1)
    """

    # 强平风险阈值
    MARGIN_LEVEL_LOW = 2.0  # 低风险阈值
    MARGIN_LEVEL_WARNING = 1.5  # 警告阈值
    MARGIN_LEVEL_DANGER = 1.3  # 危险阈值
    LIQUIDATION_LEVEL = 1.1  # 强平阈值

    def __init__(
        self,
        binance_client: Optional[Any] = None,
        config: Optional[Dict] = None
    ):
        """
        Initialize MarginAccountManager.

        Args:
            binance_client: Binance API client instance
            config: Configuration dictionary containing:
                - symbol: Trading pair (default: BTCUSDT)
                - base_leverage: Default leverage (default: 3.0)
                - max_leverage: Maximum allowed leverage (default: 5.0)
                - liquidation_warning_threshold: Warning threshold (default: 1.3)
                - liquidation_stop_threshold: Stop trading threshold (default: 1.1)

        Raises:
            ValueError: If binance_client is None.
        """
        if binance_client is None:
            raise ValueError("binance_client is required for margin account operations")

        self.binance_client = binance_client
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
        """Backward compatibility property to access binance_client."""
        return self.binance_client

    @property
    def _client(self):
        """Backward compatibility property for _client."""
        return self.binance_client

    def get_account_info(self, use_cache: bool = True) -> MarginAccountInfo:
        """
        Query cross margin account info.

        Args:
            use_cache: Whether to use cached data

        Returns:
            MarginAccountInfo containing account information,
            or raises BinanceAPIException if API call fails.
        """
        if use_cache and self._is_cache_valid():
            cached = self._cache.get("account_info")
            if isinstance(cached, MarginAccountInfo):
                return cached

        account = self.binance_client.get_margin_account()

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

    def get_margin_level(self, use_cache: bool = True) -> float:
        """
        Get margin level from cached account info.

        Args:
            use_cache: Whether to use cached data

        Returns:
            Margin level ratio. Higher is safer.
            Returns infinity if no liability.
        """
        account_info = self.get_account_info(use_cache=use_cache)
        return account_info.margin_level

    def get_available_margin(self, asset: str = DEFAULT_QUOTE_ASSET, use_cache: bool = True) -> float:
        """
        Get available margin for an asset.

        Args:
            asset: Asset symbol (e.g., 'USDT', 'BTC')
            use_cache: Whether to use cached data

        Returns:
            Available free amount for the asset.
        """
        account_info = self.get_account_info(use_cache=use_cache)
        for a in account_info.assets:
            if a.get(API_FIELD_ASSET) == asset:
                return float(a.get(API_FIELD_FREE, 0))
        return 0.0

    def get_position_value(self, asset: str, use_cache: bool = True) -> float:
        """
        Get position value for a specific asset.

        Args:
            asset: Asset symbol (e.g., 'BTC', 'ETH')
            use_cache: Whether to use cached account data

        Returns:
            Position value in USDT for the given asset.
            Returns 0.0 if asset not found or no net position.
        """
        account_info = self.get_account_info(use_cache=use_cache)
        user_assets = account_info.assets

        for item in user_assets:
            if item.get(API_FIELD_ASSET) == asset:
                net_asset = float(item.get(API_FIELD_NET_ASSET_ITEM, 0))
                if net_asset == 0:
                    return 0.0

                ticker_symbol = f"{asset}{DEFAULT_QUOTE_ASSET}"
                try:
                    ticker = self.binance_client.get_symbol_ticker(
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

    def get_borrowable_amount(self, asset: str, use_cache: bool = True) -> float:
        """
        Get borrowable amount for an asset.

        Args:
            asset: Asset symbol (e.g., 'USDT', 'BTC')
            use_cache: Whether to use cached data

        Returns:
            Maximum borrowable amount for the asset.
            Returns 0.0 if API call fails.
        """
        cache_key = f"borrowable_{asset}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if isinstance(cached, (int, float)):
                return float(cached)

        try:
            result = self.binance_client.get_max_margin_loan(
                asset=asset, symbol=self.symbol
            )
            amount = float(result.get(API_FIELD_AMOUNT, 0))
            self._cache[cache_key] = amount
            return amount
        except BinanceAPIException as e:
            logger.error(f"Failed to get borrowable amount for {asset}: {e}")
            return 0.0

    def is_liquidation_risk(self, use_cache: bool = True) -> bool:
        """
        Check if margin level is near liquidation.

        Args:
            use_cache: Whether to use cached data

        Returns:
            True if margin level is at or below warning threshold,
            False otherwise.
        """
        margin_level = self.get_margin_level(use_cache=use_cache)

        if margin_level == float('inf'):
            return False

        return margin_level <= self.liquidation_warning_threshold

    def get_liquidation_price(
        self, symbol: str, side: str, use_cache: bool = True
    ) -> Optional[float]:
        """
        Estimate liquidation price.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            side: Position side ('LONG' or 'SHORT')
            use_cache: Whether to use cached account data

        Returns:
            Estimated liquidation price, or None if cannot calculate
            (e.g., no liability or invalid side).
        """
        if side not in (PositionSide.LONG.value, PositionSide.SHORT.value):
            logger.warning(
                f"Invalid side: {side}. Use '{PositionSide.LONG.value}' or '{PositionSide.SHORT.value}'"
            )
            return None

        account_info = self.get_account_info(use_cache=use_cache)
        margin_level = account_info.margin_level

        if margin_level == float('inf'):
            return None

        if margin_level <= 1:
            return None

        try:
            ticker = self.binance_client.get_symbol_ticker(symbol=symbol)
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

    def get_position_details(self, symbol: str, use_cache: bool = True) -> Optional[MarginPosition]:
        """Get position details for a specific trading pair."""
        account_info = self.get_account_info(use_cache=use_cache)
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

    def calculate_liquidation_risk(self, use_cache: bool = True) -> Dict[str, Any]:
        """Calculate liquidation risk level."""
        info = self.get_account_info(use_cache=use_cache)
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

    def _is_cache_valid(self) -> bool:
        if self._cache_time is None:
            return False
        elapsed = (datetime.now() - self._cache_time).total_seconds()
        return elapsed < self._cache_ttl_seconds

    def _calculate_leverage_ratio(
        self, total_asset: float, net_asset: float
    ) -> float:
        if net_asset <= 0:
            return 0.0
        return total_asset / net_asset

    def _calculate_margin_level(
        self, total_asset: float, total_liability: float
    ) -> float:
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

    def refresh_cache(self) -> None:
        self._cache.clear()
        self._cache_time = None
        logger.debug("Cache refreshed")
