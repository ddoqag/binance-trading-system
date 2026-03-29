/**
 * Binance API Clients - 优化后的币安API客户端库
 * 基于tiagosiebler/binance架构设计，但完全重写实现
 */

// 基础类
const BaseRestClient = require('./base-rest-client');
const { BaseWebsocketClient, WsConnectionStateEnum } = require('./base-websocket-client');

// 具体客户端
const {
  MainClient,
  USDMClient,
  CoinMClient,
  PortfolioClient,
  BinanceBaseUrlKey
} = require('./main-client');

const { WebsocketClient, WsKey } = require('./websocket-client');

module.exports = {
  // 基础类
  BaseRestClient,
  BaseWebsocketClient,
  WsConnectionStateEnum,

  // REST API客户端
  MainClient,
  USDMClient,
  CoinMClient,
  PortfolioClient,
  BinanceBaseUrlKey,

  // WebSocket客户端
  WebsocketClient,
  WsKey
};
