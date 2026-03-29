"""全仓杠杆账户管理器

管理币安全仓杠杆账户的查询、余额、仓位和风险计算。
"""

import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime


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
    """全仓杠杆账户管理器

    负责:
    1. 查询账户信息、余额、杠杆倍数
    2. 获取持仓详情
    3. 计算保证金比率和强平风险
    4. 管理可用保证金

    Example:
        >>> from binance.client import Client
        >>> client = Client(api_key, api_secret)
        >>> manager = MarginAccountManager(binance_client=client)
        >>> info = manager.get_account_info()
        >>> print(f"当前杠杆: {info.leverage_ratio:.2f}x")
    """

    # 强平风险阈值
    MARGIN_LEVEL_LOW = 2.0  # 低风险阈值
    MARGIN_LEVEL_WARNING = 1.5  # 警告阈值
    MARGIN_LEVEL_DANGER = 1.3  # 危险阈值
    LIQUIDATION_LEVEL = 1.1  # 强平阈值

    def __init__(self, binance_client: Any):
        """
        初始化账户管理器

        Args:
            binance_client: 币安 API 客户端 (python-binance Client)

        Raises:
            ValueError: 如果未提供客户端
        """
        if binance_client is None:
            raise ValueError("binance_client is required for margin account operations")

        self._client = binance_client
        self._logger = logging.getLogger(__name__)
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 5  # 缓存5秒

    def get_account_info(self, use_cache: bool = True) -> MarginAccountInfo:
        """获取全仓杠杆账户信息"""
        if use_cache and self._is_cache_valid():
            return self._cache.get("account_info")

        try:
            account = self._client.get_margin_account()

            total_asset = float(account.get("totalAssetOfBtc", 0))
            total_liability = float(account.get("totalLiabilityOfBtc", 0))
            net_asset = float(account.get("totalNetAssetOfBtc", 0))

            # 计算杠杆倍数和保证金水平
            leverage_ratio = self._calculate_leverage_ratio(total_asset, net_asset)
            margin_level = self._calculate_margin_level(total_asset, total_liability)

            info = MarginAccountInfo(
                total_asset_btc=total_asset,
                total_liability_btc=total_liability,
                net_asset_btc=net_asset,
                leverage_ratio=leverage_ratio,
                margin_level=margin_level,
                trade_enabled=account.get("tradeEnabled", False),
                transfer_enabled=account.get("transferEnabled", False),
                borrow_enabled=account.get("borrowEnabled", False),
                assets=account.get("userAssets", []),
                updated_at=datetime.now()
            )

            self._cache["account_info"] = info
            self._cache_time = datetime.now()

            return info

        except Exception as e:
            self._logger.error(f"Failed to get margin account info: {e}")
            raise

    def get_available_margin(self, asset: str = "USDT") -> float:
        """获取指定资产的可用保证金"""
        try:
            account = self._client.get_margin_account()
            assets = account.get("userAssets", [])

            for a in assets:
                if a["asset"] == asset:
                    free = float(a.get("free", 0))
                    return free

            return 0.0

        except Exception as e:
            self._logger.error(f"Failed to get available margin for {asset}: {e}")
            return 0.0

    def get_position_details(self, symbol: str) -> Optional[MarginPosition]:
        """获取指定交易对的持仓详情"""
        try:
            account = self._client.get_margin_account()
            assets = account.get("userAssets", [])

            # 解析交易对
            base_asset, quote_asset = self._parse_symbol(symbol)

            base_info = None
            quote_info = None

            for a in assets:
                if a["asset"] == base_asset:
                    base_info = a
                elif a["asset"] == quote_asset:
                    quote_info = a

            if not base_info or not quote_info:
                return None

            base_amount = float(base_info.get("netAsset", 0))
            quote_amount = float(quote_info.get("netAsset", 0))

            # 判断持仓方向
            if base_amount > 0:
                net_position = base_amount  # 多头
            elif base_amount < 0:
                net_position = base_amount  # 空头
            else:
                return None  # 无持仓

            return MarginPosition(
                symbol=symbol,
                base_asset=base_asset,
                quote_asset=quote_asset,
                base_amount=abs(base_amount),
                quote_amount=abs(quote_amount),
                borrowed_base=float(base_info.get("borrowed", 0)),
                borrowed_quote=float(quote_info.get("borrowed", 0)),
                net_position=net_position
            )

        except Exception as e:
            self._logger.error(f"Failed to get position details for {symbol}: {e}")
            return None

    def calculate_liquidation_risk(self) -> Dict[str, Any]:
        """计算强平风险"""
        info = self.get_account_info()
        margin_level = info.margin_level

        # 判断风险等级
        if margin_level >= self.MARGIN_LEVEL_LOW:
            risk_level = "low"
        elif margin_level >= self.MARGIN_LEVEL_WARNING:
            risk_level = "medium"
        elif margin_level >= self.MARGIN_LEVEL_DANGER:
            risk_level = "high"
        else:
            risk_level = "critical"

        # 计算距离强平的安全边际
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
            "estimated_liquidation_price": None,
        }

    def get_max_borrowable(self, asset: str, symbol: str = "BTCUSDT") -> float:
        """获取最大可借贷额度"""
        try:
            result = self._client.get_max_margin_loan(asset=asset, symbol=symbol)
            return float(result.get("amount", 0))
        except Exception as e:
            self._logger.error(f"Failed to get max borrowable for {asset}: {e}")
            return 0.0

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cache_time is None:
            return False
        elapsed = (datetime.now() - self._cache_time).total_seconds()
        return elapsed < self._cache_ttl_seconds

    def _calculate_leverage_ratio(self, total_asset: float, net_asset: float) -> float:
        """计算当前杠杆倍数"""
        if net_asset <= 0:
            return 0.0
        return total_asset / net_asset

    def _calculate_margin_level(self, total_asset: float, total_liability: float) -> float:
        """计算保证金水平"""
        if total_liability <= 0:
            return float("inf")
        total_equity = total_asset - total_liability
        if total_equity <= 0:
            return 0.0
        return total_asset / total_liability

    def _parse_symbol(self, symbol: str) -> tuple:
        """解析交易对为基础资产和计价资产"""
        if symbol.endswith("USDT"):
            return symbol[:-4], "USDT"
        elif symbol.endswith("BTC"):
            return symbol[:-3], "BTC"
        elif symbol.endswith("ETH"):
            return symbol[:-3], "ETH"
        else:
            return symbol[:3], symbol[3:]

    def refresh_cache(self) -> None:
        """强制刷新缓存"""
        self._cache.clear()
        self._cache_time = None
        self._logger.debug("Cache refreshed")
