/**
 * Binance Main Client
 * 币安API客户端主类，支持现货、保证金、钱包等API
 */

const crypto = require('crypto');
const BaseRestClient = require('./base-rest-client');

const BinanceBaseUrlKey = {
  MAIN: 'main',
  USDM: 'usdm',
  COINM: 'coinm',
  PORTFOLIO: 'portfolio'
};

const BinanceBaseUrls = {
  [BinanceBaseUrlKey.MAIN]: {
    prod: 'https://api.binance.com',
    test: 'https://testnet.binance.vision'
  },
  [BinanceBaseUrlKey.USDM]: {
    prod: 'https://fapi.binance.com',
    test: 'https://testnet.binancefuture.com'
  },
  [BinanceBaseUrlKey.COINM]: {
    prod: 'https://dapi.binance.com',
    test: 'https://testnet.binancefuture.com'
  },
  [BinanceBaseUrlKey.PORTFOLIO]: {
    prod: 'https://api.binance.com',
    test: 'https://testnet.binance.vision'
  }
};

class MainClient extends BaseRestClient {
  constructor(options = {}) {
    super(BinanceBaseUrlKey.MAIN, options);
  }

  getBaseUrl(baseUrlKey) {
    const config = BinanceBaseUrls[baseUrlKey];
    const base = this.options.testnet ? config.test : config.prod;
    return base.endsWith('/') ? base.slice(0, -1) : base;
  }

  getTestnetBaseUrlKey(baseUrlKey) {
    return baseUrlKey; // 币安测试网URL与主网结构相同
  }

  async getServerTime() {
    const response = await this.get('/api/v3/time');
    return response.serverTime;
  }

  async getRESTRequestSignature(params, timestamp) {
    if (!this.options.api_secret) {
      return {
        serialisedParams: this.serialiseParams(params),
        signature: null,
        requestBody: params
      };
    }

    const queryString = this.serialiseParams({
      ...params,
      timestamp
    });

    const signature = crypto
      .createHmac('sha256', this.options.api_secret)
      .update(queryString)
      .digest('hex');

    return {
      serialisedParams: queryString,
      signature,
      requestBody: params
    };
  }

  serialiseParams(params) {
    return Object.entries(params)
      .filter(([key, value]) => value !== null && value !== undefined)
      .map(([key, value]) => {
        let processedValue = value;
        if (typeof value === 'object' && !(value instanceof Date)) {
          processedValue = JSON.stringify(value);
        }
        return `${encodeURIComponent(key)}=${encodeURIComponent(processedValue)}`;
      })
      .join('&');
  }

  // 现货API方法
  async getExchangeInfo() {
    return this.get('/api/v3/exchangeInfo');
  }

  async getOrderBook(symbol, limit = 100) {
    return this.get('/api/v3/depth', {
      symbol,
      limit
    });
  }

  async getRecentTrades(symbol, limit = 500) {
    return this.get('/api/v3/trades', {
      symbol,
      limit
    });
  }

  async getKlines(symbol, interval, options = {}) {
    const params = {
      symbol,
      interval,
      limit: options.limit || 500
    };
    if (options.startTime) {
      params.startTime = options.startTime;
    }
    if (options.endTime) {
      params.endTime = options.endTime;
    }
    return this.get('/api/v3/klines', params);
  }

  async getTicker24hr(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/api/v3/ticker/24hr', params);
  }

  async getPrice(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/api/v3/ticker/price', params);
  }

  async getBookTicker(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/api/v3/ticker/bookTicker', params);
  }

  // 账户信息（需要认证）
  async getAccount() {
    return this.getPrivate('/api/v3/account');
  }

  async getOrder(symbol, options = {}) {
    const params = {
      symbol,
      ...options
    };
    return this.getPrivate('/api/v3/order', params);
  }

  async getOpenOrders(symbol) {
    const params = symbol ? { symbol } : {};
    return this.getPrivate('/api/v3/openOrders', params);
  }

  async getAllOrders(symbol, options = {}) {
    const params = {
      symbol,
      limit: options.limit || 500,
      ...options
    };
    return this.getPrivate('/api/v3/allOrders', params);
  }

  // 下单（需要认证）
  async createOrder(symbol, side, type, options = {}) {
    const params = {
      symbol,
      side,
      type,
      ...options
    };
    return this.postPrivate('/api/v3/order', params);
  }

  async createTestOrder(symbol, side, type, options = {}) {
    const params = {
      symbol,
      side,
      type,
      ...options
    };
    return this.postPrivate('/api/v3/order/test', params);
  }

  async cancelOrder(symbol, options = {}) {
    const params = {
      symbol,
      ...options
    };
    return this.deletePrivate('/api/v3/order', params);
  }

  async cancelAllOpenOrders(symbol) {
    const params = symbol ? { symbol } : {};
    return this.deletePrivate('/api/v3/openOrders', params);
  }

  // 用户数据流
  async getUserDataStream() {
    return this.post('/api/v3/userDataStream');
  }

  async keepAliveUserDataStream(listenKey) {
    return this.put('/api/v3/userDataStream', {
      listenKey
    });
  }

  async closeUserDataStream(listenKey) {
    return this.delete('/api/v3/userDataStream', {
      listenKey
    });
  }
}

class USDMClient extends BaseRestClient {
  constructor(options = {}) {
    super(BinanceBaseUrlKey.USDM, options);
  }

  getBaseUrl(baseUrlKey) {
    const config = BinanceBaseUrls[baseUrlKey];
    const base = this.options.testnet ? config.test : config.prod;
    return base.endsWith('/') ? base.slice(0, -1) : base;
  }

  getTestnetBaseUrlKey(baseUrlKey) {
    return baseUrlKey;
  }

  async getServerTime() {
    const response = await this.get('/fapi/v1/time');
    return response.serverTime;
  }

  async getRESTRequestSignature(params, timestamp) {
    if (!this.options.api_secret) {
      return {
        serialisedParams: this.serialiseParams(params),
        signature: null,
        requestBody: params
      };
    }

    const queryString = this.serialiseParams({
      ...params,
      timestamp
    });

    const signature = crypto
      .createHmac('sha256', this.options.api_secret)
      .update(queryString)
      .digest('hex');

    return {
      serialisedParams: queryString,
      signature,
      requestBody: params
    };
  }

  serialiseParams(params) {
    return Object.entries(params)
      .filter(([key, value]) => value !== null && value !== undefined)
      .map(([key, value]) => {
        let processedValue = value;
        if (typeof value === 'object' && !(value instanceof Date)) {
          processedValue = JSON.stringify(value);
        }
        return `${encodeURIComponent(key)}=${encodeURIComponent(processedValue)}`;
      })
      .join('&');
  }

  // USDM期货API方法
  async getExchangeInfo() {
    return this.get('/fapi/v1/exchangeInfo');
  }

  async getMarkPrice(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/fapi/v1/premiumIndex', params);
  }

  async getKlines(symbol, interval, options = {}) {
    const params = {
      symbol,
      interval,
      limit: options.limit || 500
    };
    if (options.startTime) {
      params.startTime = options.startTime;
    }
    if (options.endTime) {
      params.endTime = options.endTime;
    }
    return this.get('/fapi/v1/klines', params);
  }

  async getTicker24hr(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/fapi/v1/ticker/24hr', params);
  }

  async getOrderBook(symbol, limit = 500) {
    return this.get('/fapi/v1/depth', {
      symbol,
      limit
    });
  }
}

class CoinMClient extends BaseRestClient {
  constructor(options = {}) {
    super(BinanceBaseUrlKey.COINM, options);
  }

  getBaseUrl(baseUrlKey) {
    const config = BinanceBaseUrls[baseUrlKey];
    const base = this.options.testnet ? config.test : config.prod;
    return base.endsWith('/') ? base.slice(0, -1) : base;
  }

  getTestnetBaseUrlKey(baseUrlKey) {
    return baseUrlKey;
  }

  async getServerTime() {
    const response = await this.get('/dapi/v1/time');
    return response.serverTime;
  }

  async getRESTRequestSignature(params, timestamp) {
    if (!this.options.api_secret) {
      return {
        serialisedParams: this.serialiseParams(params),
        signature: null,
        requestBody: params
      };
    }

    const queryString = this.serialiseParams({
      ...params,
      timestamp
    });

    const signature = crypto
      .createHmac('sha256', this.options.api_secret)
      .update(queryString)
      .digest('hex');

    return {
      serialisedParams: queryString,
      signature,
      requestBody: params
    };
  }

  serialiseParams(params) {
    return Object.entries(params)
      .filter(([key, value]) => value !== null && value !== undefined)
      .map(([key, value]) => {
        let processedValue = value;
        if (typeof value === 'object' && !(value instanceof Date)) {
          processedValue = JSON.stringify(value);
        }
        return `${encodeURIComponent(key)}=${encodeURIComponent(processedValue)}`;
      })
      .join('&');
  }

  // CoinM期货API方法
  async getExchangeInfo() {
    return this.get('/dapi/v1/exchangeInfo');
  }

  async getKlines(symbol, interval, options = {}) {
    const params = {
      symbol,
      interval,
      limit: options.limit || 500
    };
    if (options.startTime) {
      params.startTime = options.startTime;
    }
    if (options.endTime) {
      params.endTime = options.endTime;
    }
    return this.get('/dapi/v1/klines', params);
  }

  async getTicker24hr(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/dapi/v1/ticker/24hr', params);
  }

  async getMarkPrice(symbol) {
    const params = symbol ? { symbol } : {};
    return this.get('/dapi/v1/premiumIndex', params);
  }
}

class PortfolioClient extends BaseRestClient {
  constructor(options = {}) {
    super(BinanceBaseUrlKey.PORTFOLIO, options);
  }

  getBaseUrl(baseUrlKey) {
    const config = BinanceBaseUrls[baseUrlKey];
    const base = this.options.testnet ? config.test : config.prod;
    return base.endsWith('/') ? base.slice(0, -1) : base;
  }

  getTestnetBaseUrlKey(baseUrlKey) {
    return baseUrlKey;
  }

  async getServerTime() {
    const response = await this.get('/api/v3/time');
    return response.serverTime;
  }

  async getRESTRequestSignature(params, timestamp) {
    if (!this.options.api_secret) {
      return {
        serialisedParams: this.serialiseParams(params),
        signature: null,
        requestBody: params
      };
    }

    const queryString = this.serialiseParams({
      ...params,
      timestamp
    });

    const signature = crypto
      .createHmac('sha256', this.options.api_secret)
      .update(queryString)
      .digest('hex');

    return {
      serialisedParams: queryString,
      signature,
      requestBody: params
    };
  }

  serialiseParams(params) {
    return Object.entries(params)
      .filter(([key, value]) => value !== null && value !== undefined)
      .map(([key, value]) => {
        let processedValue = value;
        if (typeof value === 'object' && !(value instanceof Date)) {
          processedValue = JSON.stringify(value);
        }
        return `${encodeURIComponent(key)}=${encodeURIComponent(processedValue)}`;
      })
      .join('&');
  }
}

module.exports = {
  MainClient,
  USDMClient,
  CoinMClient,
  PortfolioClient,
  BinanceBaseUrlKey
};
