/**
 * Binance WebSocket Client
 * 币安WebSocket客户端，支持所有产品类型的WebSocket连接
 */

const { BaseWebsocketClient, WsConnectionStateEnum } = require('./base-websocket-client');

const WsKey = {
  MAIN_PUBLIC: 'main_public',
  MAIN_USER_DATA: 'main_user_data',
  USDM_PUBLIC: 'usdm_public',
  USDM_USER_DATA: 'usdm_user_data',
  COINM_PUBLIC: 'coinm_public',
  COINM_USER_DATA: 'coinm_user_data',
  PORTFOLIO: 'portfolio'
};

const WsUrlMap = {
  [WsKey.MAIN_PUBLIC]: {
    prod: 'wss://stream.binance.com:9443/ws',
    test: 'wss://testnet.binance.vision/ws'
  },
  [WsKey.MAIN_USER_DATA]: {
    prod: 'wss://stream.binance.com:9443/ws',
    test: 'wss://testnet.binance.vision/ws'
  },
  [WsKey.USDM_PUBLIC]: {
    prod: 'wss://fstream.binance.com/ws',
    test: 'wss://stream.binancefuture.com/ws'
  },
  [WsKey.USDM_USER_DATA]: {
    prod: 'wss://fstream.binance.com/ws',
    test: 'wss://stream.binancefuture.com/ws'
  },
  [WsKey.COINM_PUBLIC]: {
    prod: 'wss://dstream.binance.com/ws',
    test: 'wss://dstream.binancefuture.com/ws'
  },
  [WsKey.COINM_USER_DATA]: {
    prod: 'wss://dstream.binance.com/ws',
    test: 'wss://dstream.binancefuture.com/ws'
  }
};

class WebsocketClient extends BaseWebsocketClient {
  constructor(options = {}) {
    super(options);
    this.listenKeyManager = new Map();
  }

  // 抽象方法实现
  isAuthOnConnectWsKey(wsKey) {
    return [
      WsKey.MAIN_USER_DATA,
      WsKey.USDM_USER_DATA,
      WsKey.COINM_USER_DATA,
      WsKey.PORTFOLIO
    ].includes(wsKey);
  }

  isCustomReconnectionNeeded(wsKey) {
    return this.isAuthOnConnectWsKey(wsKey);
  }

  async triggerCustomReconnectionWorkflow(wsKey) {
    this.logger.info(`Custom reconnection workflow for ${wsKey}`);
    // 对于用户数据流，需要重新获取listenKey
    if (this.isAuthOnConnectWsKey(wsKey)) {
      const manager = this.listenKeyManager.get(wsKey);
      if (manager) {
        try {
          const newListenKey = await manager.refreshListenKey();
          // 使用新的listenKey重新连接
          const wsUrl = await this.getWsUrl(wsKey);
          const newWsUrl = this.replaceListenKeyInUrl(wsUrl, newListenKey);
          await this.close(wsKey, true);
          await this.connect(wsKey, newWsUrl);
          this.emit('reconnected', { wsKey, ws: this.getWs(wsKey) });
        } catch (error) {
          this.logger.error(`Custom reconnection failed for ${wsKey}:`, error);
          this.scheduleReconnect(wsKey);
        }
      }
    }
  }

  replaceListenKeyInUrl(url, listenKey) {
    const baseUrl = url.split('/ws/')[0];
    return `${baseUrl}/ws/${listenKey}`;
  }

  sendPingEvent(wsKey, ws) {
    ws.ping();
  }

  sendPongEvent(wsKey, ws) {
    ws.pong();
  }

  isWsPing(data) {
    // Binance使用WebSocket原生ping/pong帧，不需要在消息内容中判断
    return false;
  }

  isWsPong(data) {
    // Binance使用WebSocket原生ping/pong帧，不需要在消息内容中判断
    return false;
  }

  async getWsAuthRequestEvent(wsKey) {
    // Binance用户数据流不需要WebSocket认证事件，使用listenKey
    return null;
  }

  isPrivateTopicRequest(request, wsKey) {
    return this.isAuthOnConnectWsKey(wsKey);
  }

  getPrivateWSKeys() {
    return [
      WsKey.MAIN_USER_DATA,
      WsKey.USDM_USER_DATA,
      WsKey.COINM_USER_DATA,
      WsKey.PORTFOLIO
    ];
  }

  async getWsUrl(wsKey) {
    const urlConfig = WsUrlMap[wsKey];
    let baseUrl = this.options.testnet ? urlConfig.test : urlConfig.prod;
    // 确保URL格式正确，避免双斜杠
    if (baseUrl.endsWith('/')) {
      baseUrl = baseUrl.slice(0, -1);
    }

    // 对于公开流，确保URL正确（如wss://stream.binance.com:9443/ws 或 wss://testnet.binance.vision/ws）
    if ([WsKey.MAIN_PUBLIC, WsKey.MAIN_USER_DATA].includes(wsKey)) {
      return baseUrl;
    } else if ([WsKey.USDM_PUBLIC, WsKey.USDM_USER_DATA].includes(wsKey)) {
      return baseUrl;
    } else if ([WsKey.COINM_PUBLIC, WsKey.COINM_USER_DATA].includes(wsKey)) {
      return baseUrl;
    }

    return baseUrl;
  }

  getMaxTopicsPerSubscribeEvent(wsKey) {
    // Binance每个连接可以订阅多个主题
    return null;
  }

  async getWsRequestEvents(wsKey, operation, requests) {
    // Binance使用简单的订阅格式
    return requests.map((request, index) => ({
      requestKey: `${operation}-${index}-${Date.now()}`,
      requestEvent: {
        method: operation,
        params: Array.isArray(request) ? request : [request],
        id: this.getNewRequestId()
      }
    }));
  }

  resolveEmittableEvents(wsKey, event) {
    const emittableEvents = [];

    if (event.e) {
      // 有事件类型的消息
      emittableEvents.push({
        eventType: 'formattedMessage',
        event: event
      });

      if (event.e === 'executionReport' || event.e === 'accountUpdate') {
        emittableEvents.push({
          eventType: 'formattedUserDataMessage',
          event: event
        });
      }
    } else if (event.result !== undefined || event.error) {
      // 响应消息
      emittableEvents.push({
        eventType: 'response',
        event: event
      });
    } else {
      // 原始数据消息
      emittableEvents.push({
        eventType: 'message',
        event: event
      });
    }

    return emittableEvents;
  }

  // 主题订阅实现
  async requestSubscribeTopics(wsKey, topics) {
    const ws = this.getWs(wsKey);
    if (!ws) {
      throw new Error(`No connection for ${wsKey}`);
    }

    const subscribeEvent = {
      method: 'SUBSCRIBE',
      params: topics,
      id: this.getNewRequestId()
    };

    ws.send(JSON.stringify(subscribeEvent));
  }

  async requestUnsubscribeTopics(wsKey, topics) {
    const ws = this.getWs(wsKey);
    if (!ws) {
      throw new Error(`No connection for ${wsKey}`);
    }

    const unsubscribeEvent = {
      method: 'UNSUBSCRIBE',
      params: topics,
      id: this.getNewRequestId()
    };

    ws.send(JSON.stringify(unsubscribeEvent));
  }

  // 便捷订阅方法
  subscribeKline(symbol, interval, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@kline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeMiniTicker(symbol, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@miniTicker` : '!miniTicker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeTicker(symbol, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@ticker` : '!ticker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeBookTicker(symbol, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@bookTicker` : '!bookTicker';
    return this.subscribe(topic, wsKey);
  }

  subscribeDepth(symbol, level = 20, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@depth${level}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeAggTrade(symbol, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@aggTrade`;
    return this.subscribe(topic, wsKey);
  }

  subscribeTrade(symbol, wsKey = WsKey.MAIN_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@trade`;
    return this.subscribe(topic, wsKey);
  }

  subscribeUserData(listenKey, wsKey = WsKey.MAIN_USER_DATA) {
    // 用户数据流需要使用带listenKey的URL
    this.storeTopics(wsKey, ['userData']);
    const wsUrl = `${WsUrlMap[wsKey][this.options.testnet ? 'test' : 'prod']}/${listenKey}`;
    return this.connect(wsKey, wsUrl);
  }

  // 期货订阅方法
  subscribeFuturesKline(symbol, interval, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@kline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesMiniTicker(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@miniTicker` : '!miniTicker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesTicker(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@ticker` : '!ticker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesBookTicker(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@bookTicker` : '!bookTicker';
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesDepth(symbol, level = 20, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@depth${level}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesAggTrade(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@aggTrade`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesMarkPrice(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@markPrice` : '!markPrice@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesContinuousKline(pair, contractType, interval, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${pair.toLowerCase()}_${contractType.toLowerCase()}@continuousKline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesIndexPriceKline(pair, interval, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${pair.toLowerCase()}@indexPriceKline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesMarkPriceKline(pair, interval, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${pair.toLowerCase()}@markPriceKline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesLiquidationOrders(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@forceOrder` : '!forceOrder@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeFuturesCompositeIndex(symbol, wsKey = WsKey.USDM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@compositeIndex`;
    return this.subscribe(topic, wsKey);
  }

  // 币本位期货订阅方法
  subscribeCoinMKline(symbol, interval, wsKey = WsKey.COINM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@kline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMMiniTicker(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@miniTicker` : '!miniTicker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMTicker(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@ticker` : '!ticker@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMBookTicker(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@bookTicker` : '!bookTicker';
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMDepth(symbol, level = 20, wsKey = WsKey.COINM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@depth${level}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMAggTrade(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = `${symbol.toLowerCase()}@aggTrade`;
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMMarkPrice(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@markPrice` : '!markPrice@arr';
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMIndexPriceKline(pair, interval, wsKey = WsKey.COINM_PUBLIC) {
    const topic = `${pair.toLowerCase()}@indexPriceKline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMMarkPriceKline(pair, interval, wsKey = WsKey.COINM_PUBLIC) {
    const topic = `${pair.toLowerCase()}@markPriceKline_${interval}`;
    return this.subscribe(topic, wsKey);
  }

  subscribeCoinMLiquidationOrders(symbol, wsKey = WsKey.COINM_PUBLIC) {
    const topic = symbol ? `${symbol.toLowerCase()}@forceOrder` : '!forceOrder@arr';
    return this.subscribe(topic, wsKey);
  }
}

module.exports = {
  WebsocketClient,
  WsKey
};
