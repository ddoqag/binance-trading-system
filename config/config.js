/**
 * Configuration management - Node.js 配置管理
 * 使用环境变量加载敏感配置
 */

const fs = require('fs');
const path = require('path');

// 尝试加载 .env 文件
const envPath = path.join(__dirname, '..', '.env');
if (fs.existsSync(envPath)) {
  require('dotenv').config({ path: envPath });
}

/**
 * 数据库配置
 */
const dbConfig = {
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '5432', 10),
  database: process.env.DB_NAME || 'binance',
  user: process.env.DB_USER || 'postgres',
  password: process.env.DB_PASSWORD || '',
  max: 20,
  idleTimeoutMillis: 30000
};

/**
 * 币安 API 配置
 */
const binanceConfig = {
  apiKey: process.env.BINANCE_API_KEY || '',
  apiSecret: process.env.BINANCE_API_SECRET || '',
  testnet: process.env.BINANCE_TESTNET === 'true'
};

/**
 * 应用配置
 */
const appConfig = {
  defaultSymbol: process.env.DEFAULT_SYMBOL || 'BTCUSDT',
  defaultInterval: process.env.DEFAULT_INTERVAL || '1h',
  paperTrading: process.env.PAPER_TRADING !== 'false'
};

module.exports = {
  dbConfig,
  binanceConfig,
  appConfig
};
