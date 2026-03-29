/**
 * Base WebSocket Client for Binance
 * 基于tiagosiebler/binance架构的WebSocket客户端基础类
 * 包含智能重连、心跳管理、事件驱动架构
 */

const EventEmitter = require('events');
const WebSocket = require('ws');
const { HttpsProxyAgent } = require('https-proxy-agent');

const WsConnectionStateEnum = {
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  CLOSING: 'closing'
};

class BaseWebsocketClient extends EventEmitter {
  constructor(options = {}) {
    super();

    this.options = {
      pongTimeout: 5000,
      pingInterval: 10000,
      reconnectTimeout: 500,
      recvWindow: 5000,
      authPrivateConnectionsOnConnect: true,
      authPrivateRequestsIndividually: false,
      ...options,
      api_key: options?.api_key?.replace(/\\n/g, '\n'),
      api_secret: options?.api_secret?.replace(/\\n/g, '\n')
    };

    this.logger = this.createLogger();
    this.wsStore = new Map(); // wsKey -> { ws, topics, state, isAuthenticated }
    this.topicStore = new Map(); // wsKey -> Set of topics
    this.pingTimers = new Map();
    this.pongTimers = new Map();
    this.reconnectTimers = new Map();
    this.requestId = 0;
  }

  createLogger() {
    return {
      debug: (...args) => console.debug('[WS]', ...args),
      info: (...args) => console.info('[WS]', ...args),
      warn: (...args) => console.warn('[WS]', ...args),
      error: (...args) => console.error('[WS]', ...args)
    };
  }

  // 抽象方法，需要子类实现
  isAuthOnConnectWsKey(wsKey) {
    throw new Error('isAuthOnConnectWsKey must be implemented by subclass');
  }

  isCustomReconnectionNeeded(wsKey) {
    throw new Error('isCustomReconnectionNeeded must be implemented by subclass');
  }

  async triggerCustomReconnectionWorkflow(wsKey) {
    throw new Error('triggerCustomReconnectionWorkflow must be implemented by subclass');
  }

  sendPingEvent(wsKey, ws) {
    throw new Error('sendPingEvent must be implemented by subclass');
  }

  sendPongEvent(wsKey, ws) {
    throw new Error('sendPongEvent must be implemented by subclass');
  }

  isWsPing(data) {
    throw new Error('isWsPing must be implemented by subclass');
  }

  isWsPong(data) {
    throw new Error('isWsPong must be implemented by subclass');
  }

  async getWsAuthRequestEvent(wsKey) {
    throw new Error('getWsAuthRequestEvent must be implemented by subclass');
  }

  isPrivateTopicRequest(request, wsKey) {
    throw new Error('isPrivateTopicRequest must be implemented by subclass');
  }

  getPrivateWSKeys() {
    throw new Error('getPrivateWSKeys must be implemented by subclass');
  }

  async getWsUrl(wsKey) {
    throw new Error('getWsUrl must be implemented by subclass');
  }

  getMaxTopicsPerSubscribeEvent(wsKey) {
    throw new Error('getMaxTopicsPerSubscribeEvent must be implemented by subclass');
  }

  async getWsRequestEvents(wsKey, operation, requests) {
    throw new Error('getWsRequestEvents must be implemented by subclass');
  }

  resolveEmittableEvents(wsKey, event) {
    throw new Error('resolveEmittableEvents must be implemented by subclass');
  }

  // 核心WebSocket连接管理
  async connect(wsKey, customUrl = null) {
    const existingState = this.wsStore.get(wsKey);

    // 避免重复连接
    if (existingState?.state === WsConnectionStateEnum.CONNECTED ||
        existingState?.state === WsConnectionStateEnum.CONNECTING) {
      this.logger.info(`Connection already in state ${existingState.state} for ${wsKey}`);
      return existingState;
    }

    this.setWsState(wsKey, WsConnectionStateEnum.CONNECTING);
    this.logger.info(`Connecting to ${wsKey}...`);

    try {
      let url;
      const topics = Array.from(this.topicStore.get(wsKey) || []);

      if (customUrl) {
        url = customUrl;
      } else {
        const baseWsUrl = await this.getWsUrl(wsKey);

        if (topics.length > 0) {
          // 币安WebSocket流格式: wss://stream.binance.com:9443/ws/<streamName>
          // 对于多个流，格式: wss://stream.binance.com:9443/stream?streams=<stream1>/<stream2>/<stream3>
          if (topics.length === 1) {
            url = baseWsUrl + '/' + topics[0];
          } else {
            url = baseWsUrl.replace('/ws', '/stream') + '?streams=' + topics.join('/');
          }
        } else {
          // 如果没有主题，使用基础URL进行连接（测试连接是否工作）
          url = baseWsUrl;
        }
      }

      const proxyUrl = process.env.HTTPS_PROXY || process.env.https_proxy ||
                       process.env.HTTP_PROXY  || process.env.http_proxy;
      const wsOptions = proxyUrl ? { agent: new HttpsProxyAgent(proxyUrl) } : {};
      const ws = new WebSocket(url, wsOptions);

      this.setupWebSocketHandlers(wsKey, ws);
      this.wsStore.set(wsKey, {
        ws,
        state: WsConnectionStateEnum.CONNECTING,
        isAuthenticated: false,
        url
      });

      return new Promise((resolve, reject) => {
        const onOpen = () => {
          ws.removeListener('error', onError);
          resolve(this.wsStore.get(wsKey));
        };
        const onError = (err) => {
          ws.removeListener('open', onOpen);
          this.handleConnectionError(wsKey, err);
          reject(err);
        };
        ws.once('open', onOpen);
        ws.once('error', onError);
      });
    } catch (error) {
      this.handleConnectionError(wsKey, error);
      throw error;
    }
  }

  setupWebSocketHandlers(wsKey, ws) {
    ws.on('open', () => {
      this.logger.info(`WebSocket opened for ${wsKey}`);
      this.setWsState(wsKey, WsConnectionStateEnum.CONNECTED);
      this.emit('open', { wsKey, ws });

      this.startHeartbeat(wsKey, ws);
      this.authenticateConnection(wsKey);
      this.resubscribeTopics(wsKey);
    });

    ws.on('message', (data) => {
      this.handleMessage(wsKey, data);
    });

    ws.on('ping', (data) => {
      this.handlePing(wsKey, ws, data);
    });

    ws.on('pong', (data) => {
      this.handlePong(wsKey, data);
    });

    ws.on('error', (error) => {
      this.logger.error(`WebSocket error for ${wsKey}:`, error);
      this.emit('exception', { wsKey, error });
    });

    ws.on('close', (code, reason) => {
      this.handleClose(wsKey, code, reason);
    });
  }

  handleMessage(wsKey, rawData) {
    try {
      const data = this.parseMessage(rawData);

      if (this.isWsPing(data)) {
        this.handlePing(wsKey, this.getWs(wsKey), data);
        return;
      }

      if (this.isWsPong(data)) {
        this.handlePong(wsKey, data);
        return;
      }

      const emittableEvents = this.resolveEmittableEvents(wsKey, data);

      emittableEvents.forEach(emittable => {
        if (Array.isArray(emittable)) {
          emittable.forEach(e => this.emitEvent(e, wsKey));
        } else {
          this.emitEvent(emittable, wsKey);
        }
      });
    } catch (error) {
      this.logger.error(`Error processing message for ${wsKey}:`, error);
      this.emit('exception', { wsKey, error, rawData });
    }
  }

  emitEvent(emittable, wsKey) {
    const { eventType, event, isWSAPIResponse } = emittable;
    const finalEvent = { ...event, wsKey, isWSAPIResponse };
    this.emit(eventType, finalEvent);
  }

  parseMessage(rawData) {
    if (typeof rawData === 'string') {
      return JSON.parse(rawData);
    }
    return JSON.parse(rawData.toString());
  }

  // 心跳管理
  startHeartbeat(wsKey, ws) {
    this.clearHeartbeatTimers(wsKey);

    const pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        this.sendPingEvent(wsKey, ws);
        this.startPongTimeout(wsKey);
      }
    }, this.options.pingInterval);

    this.pingTimers.set(wsKey, pingTimer);
  }

  startPongTimeout(wsKey) {
    this.clearPongTimeout(wsKey);

    const pongTimer = setTimeout(() => {
      this.logger.warn(`Pong timeout for ${wsKey}, reconnecting...`);
      this.scheduleReconnect(wsKey);
    }, this.options.pongTimeout);

    this.pongTimers.set(wsKey, pongTimer);
  }

  handlePing(wsKey, ws, data) {
    this.sendPongEvent(wsKey, ws);
  }

  handlePong(wsKey, data) {
    this.clearPongTimeout(wsKey);
  }

  clearHeartbeatTimers(wsKey) {
    this.clearPingTimer(wsKey);
    this.clearPongTimeout(wsKey);
  }

  clearPingTimer(wsKey) {
    const timer = this.pingTimers.get(wsKey);
    if (timer) {
      clearInterval(timer);
      this.pingTimers.delete(wsKey);
    }
  }

  clearPongTimeout(wsKey) {
    const timer = this.pongTimers.get(wsKey);
    if (timer) {
      clearTimeout(timer);
      this.pongTimers.delete(wsKey);
    }
  }

  // 连接管理
  handleClose(wsKey, code, reason) {
    this.logger.info(`WebSocket closed for ${wsKey}: code=${code}, reason=${reason}`);
    this.clearHeartbeatTimers(wsKey);
    this.setWsState(wsKey, WsConnectionStateEnum.DISCONNECTED);
    this.emit('close', { wsKey, code, reason });

    if (code !== 1000 && reason !== 'normal') {
      this.scheduleReconnect(wsKey);
    }
  }

  handleConnectionError(wsKey, error) {
    this.logger.error(`Connection error for ${wsKey}:`, error);
    this.emit('exception', { wsKey, error });
    this.scheduleReconnect(wsKey);
  }

  scheduleReconnect(wsKey) {
    const existingTimer = this.reconnectTimers.get(wsKey);
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    this.setWsState(wsKey, WsConnectionStateEnum.RECONNECTING);
    this.emit('reconnecting', { wsKey });

    const timer = setTimeout(() => {
      this.reconnectTimers.delete(wsKey);
      this.reconnect(wsKey);
    }, this.options.reconnectTimeout);

    this.reconnectTimers.set(wsKey, timer);
  }

  async reconnect(wsKey) {
    const state = this.wsStore.get(wsKey);

    if (this.isCustomReconnectionNeeded(wsKey)) {
      await this.triggerCustomReconnectionWorkflow(wsKey);
      return;
    }

    try {
      await this.close(wsKey, true);
      await this.connect(wsKey, state?.url);
      this.emit('reconnected', { wsKey, ws: this.getWs(wsKey) });
    } catch (error) {
      this.logger.error(`Reconnect failed for ${wsKey}:`, error);
      this.scheduleReconnect(wsKey);
    }
  }

  async close(wsKey, force = false) {
    const state = this.wsStore.get(wsKey);
    if (!state) return;

    this.logger.info(`Closing connection for ${wsKey}`);
    this.setWsState(wsKey, WsConnectionStateEnum.CLOSING);
    this.clearHeartbeatTimers(wsKey);

    const reconnectTimer = this.reconnectTimers.get(wsKey);
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      this.reconnectTimers.delete(wsKey);
    }

    if (state.ws) {
      if (force) {
        state.ws.terminate();
      } else {
        state.ws.close();
      }
    }

    this.wsStore.delete(wsKey);
  }

  // 主题订阅管理
  subscribe(topics, wsKey) {
    const topicArray = Array.isArray(topics) ? topics : [topics];
    return this.subscribeTopicsForWsKey(topicArray, wsKey);
  }

  unsubscribe(topics, wsKey) {
    const topicArray = Array.isArray(topics) ? topics : [topics];
    return this.unsubscribeTopicsForWsKey(topicArray, wsKey);
  }

  async subscribeTopicsForWsKey(topics, wsKey) {
    this.storeTopics(wsKey, topics);

    const state = this.wsStore.get(wsKey);

    if (!state || state.state !== WsConnectionStateEnum.CONNECTED) {
      return this.connect(wsKey);
    }

    if (this.isPrivateWsKey(wsKey) && !state.isAuthenticated) {
      return false;
    }

    return this.requestSubscribeTopics(wsKey, topics);
  }

  async unsubscribeTopicsForWsKey(topics, wsKey) {
    this.removeTopics(wsKey, topics);

    const state = this.wsStore.get(wsKey);
    if (!state || state.state !== WsConnectionStateEnum.CONNECTED) {
      return;
    }

    if (this.isPrivateWsKey(wsKey) && !state.isAuthenticated) {
      return;
    }

    return this.requestUnsubscribeTopics(wsKey, topics);
  }

  storeTopics(wsKey, topics) {
    let existingTopics = this.topicStore.get(wsKey);
    if (!existingTopics) {
      existingTopics = new Set();
      this.topicStore.set(wsKey, existingTopics);
    }
    topics.forEach(topic => existingTopics.add(topic));
  }

  removeTopics(wsKey, topics) {
    const existingTopics = this.topicStore.get(wsKey);
    if (existingTopics) {
      topics.forEach(topic => existingTopics.delete(topic));
    }
  }

  async resubscribeTopics(wsKey) {
    const topics = this.topicStore.get(wsKey);
    if (topics && topics.size > 0) {
      this.logger.info(`Resubscribing to ${topics.size} topics for ${wsKey}`);
      await this.requestSubscribeTopics(wsKey, Array.from(topics));
    }
  }

  async requestSubscribeTopics(wsKey, topics) {
    throw new Error('requestSubscribeTopics must be implemented by subclass');
  }

  async requestUnsubscribeTopics(wsKey, topics) {
    throw new Error('requestUnsubscribeTopics must be implemented by subclass');
  }

  // 认证管理
  async authenticateConnection(wsKey) {
    if (!this.isAuthOnConnectWsKey(wsKey)) {
      return;
    }

    try {
      const authEvent = await this.getWsAuthRequestEvent(wsKey);
      const state = this.wsStore.get(wsKey);

      if (state && state.ws) {
        state.ws.send(JSON.stringify(authEvent));
        state.isAuthenticated = true;
        this.emit('authenticated', { wsKey });
      }
    } catch (error) {
      this.logger.error(`Authentication failed for ${wsKey}:`, error);
    }
  }

  isPrivateWsKey(wsKey) {
    return this.getPrivateWSKeys().includes(wsKey);
  }

  // 状态管理
  setWsState(wsKey, state) {
    const existing = this.wsStore.get(wsKey) || {};
    this.wsStore.set(wsKey, { ...existing, state });
  }

  getWs(wsKey) {
    const state = this.wsStore.get(wsKey);
    return state?.ws;
  }

  isConnected(wsKey) {
    const state = this.wsStore.get(wsKey);
    return state?.state === WsConnectionStateEnum.CONNECTED;
  }

  // 工具方法
  getNewRequestId() {
    return ++this.requestId;
  }
}

module.exports = {
  BaseWebsocketClient,
  WsConnectionStateEnum
};
