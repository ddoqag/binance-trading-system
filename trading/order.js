/**
 * 订单管理 - Node.js 版本
 */

const OrderType = Object.freeze({
  MARKET: 'MARKET',
  LIMIT: 'LIMIT',
  STOP_MARKET: 'STOP_MARKET',
  STOP_LIMIT: 'STOP_LIMIT'
});

const OrderSide = Object.freeze({
  BUY: 'BUY',
  SELL: 'SELL'
});

const OrderStatus = Object.freeze({
  NEW: 'NEW',
  PARTIALLY_FILLED: 'PARTIALLY_FILLED',
  FILLED: 'FILLED',
  CANCELED: 'CANCELED',
  REJECTED: 'REJECTED',
  PENDING_CANCEL: 'PENDING_CANCEL'
});

class Order {
  /**
   * @param {Object} config
   * @param {string} config.orderId
   * @param {string} config.symbol
   * @param {OrderSide} config.side
   * @param {OrderType} config.type
   * @param {number} config.quantity
   * @param {number} config.price
   * @param {number} config.stopPrice
   * @param {OrderStatus} config.status
   * @param {Date} config.createTime
   */
  constructor(config = {}) {
    this.orderId = config.orderId;
    this.symbol = config.symbol;
    this.side = config.side;
    this.type = config.type;
    this.quantity = config.quantity;
    this.price = config.price;
    this.stopPrice = config.stopPrice;
    this.status = config.status || OrderStatus.NEW;
    this.createTime = config.createTime || new Date();

    this.filledQuantity = 0;
    this.avgPrice = null;
    this.updateTime = null;
  }

  get isFilled() {
    return this.status === OrderStatus.FILLED;
  }

  get isActive() {
    return [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED].includes(this.status);
  }
}

module.exports = {
  Order,
  OrderType,
  OrderSide,
  OrderStatus
};
