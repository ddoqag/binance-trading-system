/**
 * Base REST API Client for Binance
 * 基于tiagosiebler/binance架构的REST API客户端基础类
 */

const axios = require('axios');
const https = require('https');

class BaseRestClient {
  constructor(baseUrlKey, options = {}, requestOptions = {}) {
    this.options = {
      recvWindow: 5000,
      syncIntervalMs: 3600000,
      strictParamValidation: false,
      disableTimeSync: true,
      beautifyResponses: true,
      keepAlive: true,
      keepAliveMsecs: 30000,
      ...options,
      api_key: options?.api_key?.replace(/\\n/g, '\n'),
      api_secret: options?.api_secret?.replace(/\\n/g, '\n')
    };

    this.globalRequestOptions = {
      timeout: 1000 * 60 * 5,
      headers: {},
      ...requestOptions
    };

    // 配置HTTP Keep-Alive
    if (this.options.keepAlive) {
      const existingHttpsAgent = this.globalRequestOptions.httpsAgent;
      const existingAgentOptions = existingHttpsAgent?.options || {};

      this.globalRequestOptions.httpsAgent = new https.Agent({
        ...existingAgentOptions,
        keepAlive: true,
        keepAliveMsecs: this.options.keepAliveMsecs
      });
    }

    this.key = this.options.api_key;
    this.secret = this.options.api_secret;

    if (this.key) {
      this.globalRequestOptions.headers['X-MBX-APIKEY'] = this.key;
    }

    this.baseUrlKey = options.testnet
      ? this.getTestnetBaseUrlKey(baseUrlKey)
      : baseUrlKey;
    this.baseUrl = this.getBaseUrl(this.baseUrlKey);

    if (this.key && !this.secret) {
      throw new Error('API Key & Secret are both required for private endpoints');
    }

    this.timeOffset = 0;
    this.syncTimePromise = null;
    this.apiLimitTrackers = {
      'x-mbx-used-weight': 0,
      'x-mbx-used-weight-1m': 0,
      'x-sapi-used-ip-weight-1m': 0,
      'x-mbx-order-count-1s': 0,
      'x-mbx-order-count-10s': 0,
      'x-mbx-order-count-1m': 0,
      'x-mbx-order-count-1h': 0,
      'x-mbx-order-count-1d': 0
    };
    this.apiLimitLastUpdated = Date.now();

    // 启动时间同步（如果启用）
    if (!this.options.disableTimeSync) {
      this.syncTime();
      this.timeSyncInterval = setInterval(() => this.syncTime(), this.options.syncIntervalMs);
    }
  }

  getBaseUrlKey() {
    return this.baseUrlKey;
  }

  getRateLimitStates() {
    return {
      ...this.apiLimitTrackers,
      lastUpdated: this.apiLimitLastUpdated
    };
  }

  getTimeOffset() {
    return this.timeOffset;
  }

  setTimeOffset(value) {
    this.timeOffset = value;
  }

  async get(endpoint, params = {}) {
    return this._call('GET', endpoint, params);
  }

  async getPrivate(endpoint, params = {}) {
    return this._call('GET', endpoint, params, true);
  }

  async post(endpoint, params = {}) {
    return this._call('POST', endpoint, params);
  }

  async postPrivate(endpoint, params = {}) {
    return this._call('POST', endpoint, params, true);
  }

  async put(endpoint, params = {}) {
    return this._call('PUT', endpoint, params);
  }

  async putPrivate(endpoint, params = {}) {
    return this._call('PUT', endpoint, params, true);
  }

  async delete(endpoint, params = {}) {
    return this._call('DELETE', endpoint, params);
  }

  async deletePrivate(endpoint, params = {}) {
    return this._call('DELETE', endpoint, params, true);
  }

  async _call(method, endpoint, params = {}, isPrivate = false) {
    const timestamp = Date.now() + (this.getTimeOffset() || 0);

    if (isPrivate && (!this.key || !this.secret)) {
      throw new Error('Private endpoints require api and private keys to be set');
    }

    const { serialisedParams, signature, requestBody } =
      await this.getRESTRequestSignature(params, timestamp);

    const baseUrl = this.baseUrl;
    const options = {
      ...this.globalRequestOptions,
      url: baseUrl + endpoint,
      method: method,
      json: true
    };

    if (isPrivate) {
      options.url += '?' + [serialisedParams, 'signature=' + signature].join('&');
    } else if (method === 'GET' || method === 'DELETE') {
      options.params = params;
    } else {
      options.data = this.serialiseParams(requestBody);
    }

    try {
      const response = await axios(options);
      this.updateApiLimitState(response.headers);

      if (response.status === 200) {
        return this.beautifyResponse(response.data);
      }

      throw response;
    } catch (error) {
      this.handleApiError(error);
    }
  }

  updateApiLimitState(headers) {
    this.apiLimitLastUpdated = Date.now();

    Object.keys(this.apiLimitTrackers).forEach(key => {
      if (headers[key]) {
        this.apiLimitTrackers[key] = parseInt(headers[key], 10);
      }
    });
  }

  handleApiError(error) {
    if (error.response) {
      const { status, data } = error.response;
      console.error(`API Error ${status}:`, data);

      if (status === 429) {
        console.warn('Rate limit exceeded - consider adding delay');
      }
    } else if (error.request) {
      console.error('No response received from API');
    } else {
      console.error('Error preparing request:', error.message);
    }

    throw error;
  }

  beautifyResponse(data) {
    if (!this.options.beautifyResponses) {
      return data;
    }
    // 这里可以添加响应美化逻辑，比如将单字母键转换为描述性单词
    return data;
  }

  // 抽象方法，需要子类实现
  getBaseUrl(baseUrlKey) {
    throw new Error('getBaseUrl must be implemented by subclass');
  }

  getTestnetBaseUrlKey(baseUrlKey) {
    throw new Error('getTestnetBaseUrlKey must be implemented by subclass');
  }

  async getServerTime() {
    throw new Error('getServerTime must be implemented by subclass');
  }

  async syncTime() {
    try {
      const serverTime = await this.getServerTime();
      const localTime = Date.now();
      this.timeOffset = serverTime - localTime;
      console.debug(`Time sync completed - offset: ${this.timeOffset}ms`);
    } catch (error) {
      console.warn('Time sync failed:', error.message);
    }
  }

  async getRESTRequestSignature(params, timestamp) {
    throw new Error('getRESTRequestSignature must be implemented by subclass');
  }

  serialiseParams(params) {
    return params;
  }
}

module.exports = BaseRestClient;
