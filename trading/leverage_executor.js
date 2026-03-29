/**
 * 杠杆交易执行器 - Node.js 版本
 * 支持全仓杠杆和做空功能
 */

const { Order, OrderType, OrderSide, OrderStatus } = require('./order');

class LeveragePosition {
  /**
   * @param {string} symbol
   * @param {number} position - 持仓量：正数=多头，负数=空头
   * @param {number} entryPrice
   * @param {number} leverage
   * @param {number} margin
   * @param {number} availableMargin
   * @param {number} unrealizedPnl
   * @param {number} liquidationPrice
   */
  constructor(symbol, position, entryPrice, leverage, margin, availableMargin, unrealizedPnl, liquidationPrice) {
    this.symbol = symbol;
    this.position = position;
    this.entryPrice = entryPrice;
    this.leverage = leverage;
    this.margin = margin;
    this.availableMargin = availableMargin;
    this.unrealizedPnl = unrealizedPnl;
    this.liquidationPrice = liquidationPrice;
  }
}

class LeverageTradingExecutor {
  /**
   * @param {Object} config
   * @param {number} config.initialMargin
   * @param {number} config.maxLeverage
   * @param {number} config.maintenanceMarginRate
   * @param {boolean} config.isPaperTrading
   * @param {number} config.commissionRate
   * @param {number} config.slippage
   * @param {Object} config.binanceClient
   */
  constructor(config = {}) {
    this.initialMargin = config.initialMargin || 10000;
    this.maxLeverage = config.maxLeverage || 10.0;
    this.maintenanceMarginRate = config.maintenanceMarginRate || 0.005;
    this.isPaperTrading = config.isPaperTrading !== false;
    this.commissionRate = config.commissionRate || 0.001;
    this.slippage = config.slippage || 0.0005;
    this.binanceClient = config.binanceClient;

    this.availableBalance = this.initialMargin;
    this.totalBalance = this.initialMargin;
    this.positions = {};
    this.orders = {};
    this.orderHistory = [];
    this._orderCounter = 0;
    this.liquidationRisk = false;

    if (!this.isPaperTrading && !this.binanceClient) {
      throw new Error('binanceClient required for real leverage trading');
    }
  }

  createOrderId() {
    this._orderCounter += 1;
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
    const timeStr = now.toTimeString().slice(0, 8).replace(/:/g, '');
    return `LEV_${dateStr}_${timeStr}_${this._orderCounter.toString().padStart(6, '0')}`;
  }

  _calculateLiquidationPrice(symbol, position, entryPrice, leverage) {
    if (position === 0) return 0;

    const currentPos = this.positions[symbol];
    if (!currentPos) return 0;

    if (position > 0) {
      return entryPrice * (1 - 1 / leverage);
    } else {
      return entryPrice * (1 + 1 / leverage);
    }
  }

  calculatePositionSize(symbol, side, currentPrice, leverage, marginFraction = 0.9) {
    const availableForTrade = this.availableBalance * marginFraction;
    const notionalValue = availableForTrade * leverage;
    let quantity = notionalValue / currentPrice;

    if (this.positions[symbol]) {
      const currentPos = this.positions[symbol];
      if (
        (side === OrderSide.BUY && currentPos.position > 0) ||
        (side === OrderSide.SELL && currentPos.position < 0)
      ) {
        const totalNotional = Math.abs(currentPos.position * currentPrice) + notionalValue;
        const requiredMargin = totalNotional / leverage;

        if (requiredMargin > this.totalBalance * marginFraction) {
          const maxNotional = this.totalBalance * leverage * marginFraction;
          const remaining = maxNotional - Math.abs(currentPos.position * currentPrice);
          quantity = remaining / currentPrice;
        }
      }
    }

    return Math.max(0, quantity);
  }

  placeOrder(symbol, side, orderType, quantity, leverage = 1.0, price = null, stopPrice = null, currentPrice = null) {
    if (leverage <= 0 || leverage > this.maxLeverage) {
      throw new Error(`Leverage must be between 1 and ${this.maxLeverage}`);
    }

    const orderId = this.createOrderId();
    const order = new Order({
      orderId,
      symbol,
      side,
      type: orderType,
      quantity,
      price,
      stopPrice,
      status: OrderStatus.NEW,
      createTime: new Date()
    });

    if (this.isPaperTrading) {
      this._simulateFill(order, leverage, currentPrice);
    } else {
      this._executeRealOrder(order, leverage);
    }

    this.orders[orderId] = order;
    this.orderHistory.push(order);
    return order;
  }

  _simulateFill(order, leverage, currentPrice) {
    if (currentPrice === null) {
      console.warn('Current price not provided for paper trading');
      order.status = OrderStatus.REJECTED;
      return order;
    }

    let execPrice;
    if (order.side === OrderSide.BUY) {
      execPrice = currentPrice * (1 + this.slippage);
    } else {
      execPrice = currentPrice * (1 - this.slippage);
    }

    if (order.type === OrderType.MARKET) {
      order.avgPrice = execPrice;
      order.filledQuantity = order.quantity;
      order.status = OrderStatus.FILLED;
    } else if (order.type === OrderType.LIMIT) {
      if (
        (order.side === OrderSide.BUY && execPrice <= order.price) ||
        (order.side === OrderSide.SELL && execPrice >= order.price)
      ) {
        order.avgPrice = order.price;
        order.filledQuantity = order.quantity;
        order.status = OrderStatus.FILLED;
      } else {
        order.status = OrderStatus.NEW;
      }
    }

    order.updateTime = new Date();

    if (order.status === OrderStatus.FILLED) {
      this._updatePositionAfterFill(order, leverage);
    }

    return order;
  }

  _updatePositionAfterFill(order, leverage) {
    const { symbol, filledQuantity: quantity, avgPrice: price, side } = order;

    const commission = quantity * price * this.commissionRate;
    this.availableBalance -= commission;
    this.totalBalance -= commission;

    const positionChange = side === OrderSide.BUY ? quantity : -quantity;

    if (!this.positions[symbol] || this.positions[symbol].position === 0) {
      const newPosition = new LeveragePosition(
        symbol,
        positionChange,
        price,
        leverage,
        Math.abs(positionChange) * price / leverage,
        this.availableBalance,
        0.0,
        this._calculateLiquidationPrice(symbol, positionChange, price, leverage)
      );
      this.positions[symbol] = newPosition;
      this.availableBalance -= newPosition.margin;
    } else {
      const pos = this.positions[symbol];

      if (
        (pos.position > 0 && positionChange > 0) ||
        (pos.position < 0 && positionChange < 0)
      ) {
        const totalQuantity = Math.abs(pos.position) + Math.abs(positionChange);
        const totalCost = Math.abs(pos.position) * pos.entryPrice + Math.abs(positionChange) * price;
        pos.entryPrice = totalCost / totalQuantity;
        pos.position += positionChange;
        pos.margin = Math.abs(pos.position) * price / leverage;
        this.availableBalance -= Math.abs(positionChange) * price / leverage;
      } else {
        const netChange = pos.position + positionChange;

        if (Math.abs(netChange) < Math.abs(pos.position)) {
          const closeQuantity = Math.abs(positionChange);
          const pnl = closeQuantity * (1 / pos.position) * (price - pos.entryPrice) * Math.abs(pos.position);

          pos.position = netChange;
          pos.margin = Math.abs(pos.position) * price / leverage;
          this.availableBalance += Math.abs(positionChange) * price / leverage;
          this.availableBalance += pnl;
          this.totalBalance += pnl;
        } else {
          const totalPnl = pos.position * (price - pos.entryPrice);
          this.availableBalance += pos.margin;
          this.availableBalance += totalPnl;
          this.totalBalance += totalPnl;

          pos.position = netChange;
          pos.entryPrice = price;
          pos.margin = Math.abs(netChange) * price / leverage;
          this.availableBalance -= pos.margin;
        }
      }
    }

    if (this.positions[symbol]) {
      const pos = this.positions[symbol];
      if (pos.position !== 0) {
        pos.unrealizedPnl = pos.position * (price - pos.entryPrice);
        pos.liquidationPrice = this._calculateLiquidationPrice(symbol, pos.position, pos.entryPrice, leverage);
        pos.availableMargin = this.availableBalance;
      }
    }

    this._checkLiquidationRisk();
  }

  _executeRealOrder(order, leverage) {
    if (!this.binanceClient) {
      order.status = OrderStatus.REJECTED;
      return order;
    }
    throw new Error('Real leverage trading not implemented yet');
  }

  _checkLiquidationRisk() {
    this.liquidationRisk = false;
    for (const symbol in this.positions) {
      const pos = this.positions[symbol];
      if (pos.position === 0) continue;

      if (
        Math.abs(pos.position) * pos.entryPrice / pos.leverage * this.maintenanceMarginRate >
        this.totalBalance
      ) {
        this.liquidationRisk = true;
        console.warn(`Liquidation risk detected for ${symbol}!`);
      }
    }
  }

  calculateUnrealizedPnl(symbol, currentPrice) {
    if (!this.positions[symbol]) return 0;

    const pos = this.positions[symbol];
    if (pos.position === 0) return 0;

    return pos.position * (currentPrice - pos.entryPrice);
  }

  closePosition(symbol, currentPrice, leverage = 1.0) {
    if (!this.positions[symbol] || this.positions[symbol].position === 0) {
      console.warn(`No position to close for ${symbol}`);
      return null;
    }

    const pos = this.positions[symbol];
    const quantity = Math.abs(pos.position);
    const side = pos.position > 0 ? OrderSide.SELL : OrderSide.BUY;

    return this.placeOrder(
      symbol,
      side,
      OrderType.MARKET,
      quantity,
      leverage,
      null,
      null,
      currentPrice
    );
  }

  forceLiquidation(symbol, currentPrice) {
    if (!this.positions[symbol]) return;

    const pos = this.positions[symbol];
    const pnl = pos.position * (currentPrice - pos.entryPrice);
    this.totalBalance += pnl;
    this.availableBalance += pos.margin;

    this.positions[symbol].position = 0;
    this.positions[symbol].margin = 0;
    this.positions[symbol].unrealizedPnl = 0;

    this.liquidationRisk = false;
    console.error(`Position liquidated for ${symbol} at ${currentPrice}`);
  }

  getBalanceInfo() {
    let totalPositionValue = 0;
    let totalUnrealizedPnl = 0;

    for (const symbol in this.positions) {
      const pos = this.positions[symbol];
      if (pos.position !== 0) {
        totalPositionValue += Math.abs(pos.position) * pos.entryPrice;
        totalUnrealizedPnl += pos.unrealizedPnl;
      }
    }

    return {
      availableBalance: this.availableBalance,
      totalBalance: this.totalBalance,
      totalPnl: this.totalBalance - this.initialMargin,
      unrealizedPnl: totalUnrealizedPnl,
      marginUsed: Object.values(this.positions).reduce((sum, pos) => sum + pos.margin, 0),
      marginAvailable: this.availableBalance,
      totalNotionalValue: totalPositionValue,
      liquidationRisk: this.liquidationRisk
    };
  }

  getPositionInfo(symbol) {
    return this.positions[symbol];
  }

  getAllPositions() {
    return Object.values(this.positions);
  }

  getOrderHistory() {
    return [...this.orderHistory];
  }

  getOpenOrders(symbol = null) {
    const orders = Object.values(this.orders).filter(
      o => o.status === OrderStatus.NEW || o.status === OrderStatus.PARTIALLY_FILLED
    );
    if (symbol) {
      return orders.filter(o => o.symbol === symbol);
    }
    return orders;
  }
}

module.exports = {
  LeverageTradingExecutor,
  LeveragePosition
};
