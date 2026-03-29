#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杠杆交易执行器 - 支持全仓杠杆和做空功能（仅实盘）
"""

import logging
import math
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass

from .order import Order, OrderType, OrderSide, OrderStatus


@dataclass
class LeveragePosition:
    """杠杆持仓信息"""
    symbol: str
    position: float  # 持仓量：正数=多头，负数=空头
    entry_price: float  # 平均持仓价格
    leverage: float  # 杠杆倍数
    margin: float  # 已使用保证金
    available_margin: float  # 可用保证金
    unrealized_pnl: float  # 未实现盈亏
    liquidation_price: float  # 强平价格


class LeverageTradingExecutor:
    """杠杆交易执行器 - 支持全仓杠杆和做空（仅实盘）"""

    def __init__(self,
                 initial_margin: float = 10000,
                 max_leverage: float = 10.0,
                 maintenance_margin_rate: float = 0.005,
                 commission_rate: float = 0.001,
                 slippage: float = 0.0005,
                 binance_client=None):
        """
        初始化杠杆交易执行器

        Args:
            initial_margin: 初始保证金
            max_leverage: 最大杠杆倍数（默认10x）
            maintenance_margin_rate: 维持保证金率（默认0.5%）
            commission_rate: 手续费率
            slippage: 滑点率
            binance_client: 币安 API 客户端（实盘必需）
        """
        self.initial_margin = initial_margin
        self.max_leverage = max_leverage
        self.maintenance_margin_rate = maintenance_margin_rate
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.binance_client = binance_client

        # 状态管理
        self.available_balance = initial_margin
        self.total_balance = initial_margin
        self.positions: Dict[str, LeveragePosition] = {}
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []

        self.logger = logging.getLogger('LeverageTradingExecutor')
        self._order_counter = 0

        # 强平风险检测
        self.liquidation_risk = False

        if binance_client is None:
            raise ValueError("binance_client required for real leverage trading")

        self.logger.info(f"Leverage Trading Executor initialized (Max Leverage: {max_leverage}x)")
        self.logger.warning("REAL LEVERAGE TRADING MODE - USING REAL MONEY!")

    def create_order_id(self) -> str:
        """生成订单 ID"""
        self._order_counter += 1
        return f"LEV_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._order_counter:06d}"

    def _calculate_liquidation_price(self, symbol: str,
                                    position: float,
                                    entry_price: float,
                                    leverage: float) -> float:
        """计算强平价格"""
        if position == 0:
            return 0.0

        current_pos = self.positions.get(symbol)
        if not current_pos:
            return 0.0

        # 全仓模式强平价格计算公式
        # 多头: Liq Price = Entry Price * (1 - 1/Leverage)
        # 空头: Liq Price = Entry Price * (1 + 1/Leverage)
        if position > 0:
            return entry_price * (1 - 1/leverage)
        else:
            return entry_price * (1 + 1/leverage)

    def calculate_position_size(self, symbol: str,
                               side: OrderSide,
                               current_price: float,
                               leverage: float,
                               margin_fraction: float = 0.9) -> float:
        """
        计算可开仓大小

        Args:
            symbol: 交易对
            side: 买卖方向（做多/做空）
            current_price: 当前价格
            leverage: 使用的杠杆倍数
            margin_fraction: 使用保证金的比例（默认90%）

        Returns:
            可开仓数量
        """
        # 计算可用资金
        available_for_trade = self.available_balance * margin_fraction

        # 全仓模式下的最大可开仓量
        notional_value = available_for_trade * leverage
        quantity = notional_value / current_price

        # 检查现持仓，防止过度开仓
        if symbol in self.positions:
            current_pos = self.positions[symbol]
            # 同一方向加仓或反向开仓需要考虑风险
            if (side == OrderSide.BUY and current_pos.position > 0) or \
               (side == OrderSide.SELL and current_pos.position < 0):
                # 同向加仓，计算总风险
                total_notional = abs(current_pos.position * current_price) + notional_value
                required_margin = total_notional / leverage

                if required_margin > self.total_balance * margin_fraction:
                    max_notional = self.total_balance * leverage * margin_fraction
                    remaining = max_notional - abs(current_pos.position * current_price)
                    quantity = remaining / current_price
            else:
                # 反向开仓，计算净风险
                pass

        return max(0, quantity)

    def place_order(self, symbol: str,
                   side: OrderSide,
                   order_type: OrderType,
                   quantity: float,
                   leverage: float = 1.0,
                   price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   current_price: Optional[float] = None) -> Order:
        """
        下单（支持做多/做空）

        Args:
            symbol: 交易对
            side: 买卖方向（BUY=做多，SELL=做空）
            order_type: 订单类型
            quantity: 数量
            leverage: 杠杆倍数（默认1x）
            price: 限价单价格
            stop_price: 止损/止盈价格
            current_price: 当前市价（预留参数）

        Returns:
            订单对象
        """
        # 验证杠杆范围
        if leverage <= 0 or leverage > self.max_leverage:
            raise ValueError(f"Leverage must be between 1 and {self.max_leverage}")

        order_id = self.create_order_id()
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.NEW,
            create_time=datetime.now()
        )

        self.logger.info(f"Placing {leverage}x leverage order: "
                       f"{side.value} {quantity} {symbol} @ {price or 'MARKET'}")

        # 实盘下单
        order = self._execute_real_order(order, leverage)

        self.orders[order_id] = order
        self.order_history.append(order)

        return order

    def _execute_real_order(self, order: Order, leverage: float) -> Order:
        """
        实盘杠杆交易下单 - 使用币安合约API

        流程：
        1. 检查币安客户端连接
        2. 设置合约杠杆倍数
        3. 转换订单参数
        4. 调用合约下单API
        5. 处理响应并更新订单状态
        """
        if self.binance_client is None:
            self.logger.error("Binance client not provided for real trading")
            order.status = OrderStatus.REJECTED
            return order

        try:
            # 获取币安底层客户端
            # 兼容两种情况：直接传入 Client 对象，或包装后的客户端
            if hasattr(self.binance_client, '_client'):
                client = self.binance_client._client
            else:
                client = self.binance_client
            if client is None:
                raise ValueError("Binance client not connected")

            symbol = order.symbol
            side = 'BUY' if order.side == OrderSide.BUY else 'SELL'

            # 步骤1: 设置合约杠杆（幂等操作，多次设置无影响）
            try:
                client.futures_change_leverage(
                    symbol=symbol,
                    leverage=int(leverage)
                )
                self.logger.info(f"Set futures leverage: {symbol} = {leverage}x")
            except Exception as e:
                self.logger.warning(f"Failed to set leverage (may already set): {e}")

            # 步骤2: 检查并切换合约仓位模式为双向持仓
            try:
                # 设置为双向持仓模式（支持同时持有多空仓位）
                client.futures_change_position_mode(dualSidePosition=True)
            except Exception as e:
                # 可能已经设置过了，忽略错误
                pass

            # 步骤2b: 设置保证金模式为全仓 (CROSSED)
            try:
                client.futures_change_margin_type(
                    symbol=symbol,
                    marginType='CROSSED'  # 全仓模式，所有仓位共享保证金
                )
                self.logger.info(f"Set margin type to CROSSED for {symbol}")
            except Exception as e:
                # 可能已经设置过了，或账户已处于该模式
                self.logger.debug(f"Margin type setting (may already CROSSED): {e}")

            # 步骤3: 计算并格式化数量精度
            quantity = self._format_quantity(symbol, order.quantity, client)
            if quantity <= 0:
                raise ValueError(f"Invalid quantity after formatting: {quantity}")

            # 步骤4: 构建合约订单参数
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': client.FUTURE_ORDER_TYPE_MARKET,
                'quantity': quantity,
                'positionSide': 'LONG' if order.side == OrderSide.BUY else 'SHORT'
            }

            self.logger.info(
                f"Executing FUTURES order: {side} {quantity} {symbol} "
                f"@ MARKET (Leverage: {leverage}x, Position: {order_params['positionSide']})"
            )

            # 步骤5: 调用币安合约下单API
            result = client.futures_create_order(**order_params)

            # 步骤6: 处理响应
            if result and 'orderId' in result:
                order.order_id = str(result['orderId'])
                order.status = OrderStatus.FILLED if result.get('status') == 'FILLED' else OrderStatus.NEW

                # 获取成交详情
                if 'avgPrice' in result and result['avgPrice']:
                    order.avg_price = float(result['avgPrice'])
                elif 'price' in result and result['price']:
                    order.avg_price = float(result['price'])

                if 'executedQty' in result:
                    order.filled_quantity = float(result['executedQty'])

                self.logger.info(
                    f"Futures order placed successfully: {order.order_id}, "
                    f"status: {result.get('status')}, avg_price: {order.avg_price}"
                )

                # 更新持仓（实盘模式下立即同步持仓状态）
                self._sync_position_from_exchange(symbol, client)

            else:
                order.status = OrderStatus.REJECTED
                self.logger.error(f"Unexpected response from Binance: {result}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            self.logger.error(f"Failed to execute real futures order: {e}")

        order.update_time = datetime.now()
        return order

    def _format_quantity(self, symbol: str, quantity: float, client) -> float:
        """根据交易对的精度要求格式化数量"""
        try:
            # 获取合约交易对信息
            info = client.futures_exchange_info()
            step_size = 0.001  # 默认精度

            for s in info['symbols']:
                if s['symbol'] == symbol:
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                            break
                    break

            # 根据精度截断数量（向下取整，避免超限）
            precision = len(str(step_size).split('.')[-1].rstrip('0'))
            formatted = float(f"{quantity:.{precision}f}")

            # 确保不小于最小下单量
            min_qty = step_size
            if formatted < min_qty:
                self.logger.warning(f"Quantity {formatted} below min {min_qty}, adjusting")
                return min_qty

            return formatted

        except Exception as e:
            self.logger.warning(f"Failed to format quantity, using original: {e}")
            return quantity

    def _sync_position_from_exchange(self, symbol: str, client):
        """从交易所同步持仓信息"""
        try:
            positions = client.futures_position_information(symbol=symbol)
            for pos in positions:
                if pos['symbol'] == symbol:
                    position_amt = float(pos.get('positionAmt', 0))
                    if position_amt != 0:
                        self.positions[symbol] = LeveragePosition(
                            symbol=symbol,
                            position=position_amt,
                            entry_price=float(pos.get('entryPrice', 0)),
                            leverage=float(pos.get('leverage', 1)),
                            margin=float(pos.get('isolatedMargin', 0)) if pos.get('isolatedMargin') else abs(position_amt) * float(pos.get('entryPrice', 0)) / float(pos.get('leverage', 1)),
                            available_margin=self.available_balance,
                            unrealized_pnl=float(pos.get('unrealizedProfit', 0)),
                            liquidation_price=float(pos.get('liquidationPrice', 0))
                        )
                        self.logger.info(
                            f"Synced position from exchange: {symbol} "
                            f"position={position_amt}, entry={pos.get('entryPrice')}"
                        )
                    break
        except Exception as e:
            self.logger.warning(f"Failed to sync position from exchange: {e}")

    def _check_liquidation_risk(self):
        """检查强平风险"""
        self.liquidation_risk = False

        for symbol, pos in self.positions.items():
            if pos.position == 0:
                continue

            # 检查维持保证金
            if abs(pos.position) * pos.entry_price / pos.leverage * \
               self.maintenance_margin_rate > self.total_balance:
                self.liquidation_risk = True
                self.logger.warning(f"Liquidation risk detected for {symbol}!")

    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """计算未实现盈亏"""
        if symbol not in self.positions:
            return 0.0

        pos = self.positions[symbol]
        if pos.position == 0:
            return 0.0

        return pos.position * (current_price - pos.entry_price)

    def calculate_available_leverage(self, symbol: str,
                                   current_price: float,
                                   side: OrderSide) -> float:
        """计算可用杠杆倍数"""
        if symbol not in self.positions:
            return self.max_leverage

        pos = self.positions[symbol]
        notional_value = abs(pos.position) * current_price
        used_margin = notional_value / pos.leverage

        available_margin = self.total_balance - used_margin

        if available_margin <= 0:
            return 0.0

        if side == OrderSide.BUY and pos.position > 0 or \
           side == OrderSide.SELL and pos.position < 0:
            # 同向加仓
            return min(self.max_leverage,
                      (self.total_balance / used_margin) * pos.leverage)
        else:
            # 反向开仓
            required_margin_for_close = abs(pos.position) * current_price / pos.leverage
            remaining_margin = available_margin + required_margin_for_close

            if remaining_margin <= 0:
                return 0.0

            return min(self.max_leverage,
                      self.total_balance / remaining_margin)

    def close_position(self, symbol: str,
                     current_price: Optional[float] = None,
                     leverage: float = 1.0) -> Optional[Order]:
        """
        平仓（支持反向平仓）

        Args:
            symbol: 交易对
            current_price: 当前市价
            leverage: 杠杆倍数

        Returns:
            平仓订单对象
        """
        if symbol not in self.positions or self.positions[symbol].position == 0:
            self.logger.warning(f"No position to close for {symbol}")
            return None

        pos = self.positions[symbol]
        quantity = abs(pos.position)
        side = OrderSide.SELL if pos.position > 0 else OrderSide.BUY

        return self.place_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=current_price
        )

    def force_liquidation(self, symbol: str, current_price: float):
        """强制平仓"""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]

        # 平仓盈亏
        pnl = pos.position * (current_price - pos.entry_price)
        self.total_balance += pnl

        # 释放保证金
        self.available_balance += pos.margin

        # 清除持仓
        self.positions[symbol].position = 0
        self.positions[symbol].margin = 0
        self.positions[symbol].unrealized_pnl = 0

        self.liquidation_risk = False

        self.logger.critical(f"Position liquidated for {symbol} at {current_price}")

    def get_balance_info(self) -> Dict:
        """获取账户余额信息"""
        total_position_value = 0
        total_unrealized_pnl = 0

        for pos in self.positions.values():
            if pos.position != 0:
                total_position_value += abs(pos.position) * pos.entry_price
                total_unrealized_pnl += pos.unrealized_pnl

        return {
            'available_balance': self.available_balance,
            'total_balance': self.total_balance,
            'total_pnl': self.total_balance - self.initial_margin,
            'unrealized_pnl': total_unrealized_pnl,
            'margin_used': sum(pos.margin for pos in self.positions.values()),
            'margin_available': self.available_balance,
            'total_notional_value': total_position_value,
            'liquidation_risk': self.liquidation_risk
        }

    def get_position_info(self, symbol: str) -> Optional[LeveragePosition]:
        """获取持仓信息"""
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[LeveragePosition]:
        """获取所有持仓"""
        return list(self.positions.values())

    def get_order_history(self) -> List[Order]:
        """获取订单历史"""
        return self.order_history.copy()

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未完成订单"""
        orders = [o for o in self.orders.values()
                 if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
