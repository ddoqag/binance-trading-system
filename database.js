// @ts-check
const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');

/**
 * PostgreSQL 数据库配置 - 从环境变量加载
 */
const { dbConfig } = require('./config/config.js');

// 创建连接池
const pool = new Pool(dbConfig);

/**
 * 初始化数据库表结构
 */
async function initDatabase() {
  console.log('正在初始化数据库...');

  const client = await pool.connect();

  try {
    // ============================================
    // 决策：使用分区表 + TIMESTAMPTZ + 覆盖索引
    // ============================================

    // 创建交易对元数据表
    await client.query(`
      CREATE TABLE IF NOT EXISTS symbols (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL UNIQUE,
        base_asset VARCHAR(10) NOT NULL,
        quote_asset VARCHAR(10) NOT NULL,
        status VARCHAR(20) NOT NULL,
        tick_size NUMERIC(20, 8),
        step_size NUMERIC(20, 8),
        min_qty NUMERIC(20, 8),
        max_qty NUMERIC(20, 8),
        is_active BOOLEAN DEFAULT true,
        listed_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // 创建交易日历表
    await client.query(`
      CREATE TABLE IF NOT EXISTS trade_calendar (
        id SERIAL PRIMARY KEY,
        exchange VARCHAR(20) NOT NULL,
        trade_date DATE NOT NULL,
        is_trading BOOLEAN NOT NULL,
        is_half_day BOOLEAN DEFAULT false,
        next_trading_date DATE,
        prev_trading_date DATE,
        UNIQUE(exchange, trade_date)
      );
    `);

    // 创建 K 线数据表（分区父表）
    await client.query(`
      CREATE TABLE IF NOT EXISTS klines (
        id BIGSERIAL,
        symbol VARCHAR(20) NOT NULL,
        interval VARCHAR(10) NOT NULL,
        open_time TIMESTAMPTZ NOT NULL,
        open NUMERIC(20, 8) NOT NULL,
        high NUMERIC(20, 8) NOT NULL,
        low NUMERIC(20, 8) NOT NULL,
        close NUMERIC(20, 8) NOT NULL,
        volume NUMERIC(30, 8) NOT NULL,
        close_time TIMESTAMPTZ NOT NULL,
        quote_volume NUMERIC(30, 8) NOT NULL,
        trades INTEGER NOT NULL,
        taker_buy_base_volume NUMERIC(30, 8) NOT NULL,
        taker_buy_quote_volume NUMERIC(30, 8) NOT NULL,
        is_complete BOOLEAN DEFAULT true,
        data_source VARCHAR(20) DEFAULT 'binance_api',
        recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // 注意：PostgreSQL 11+ 支持分区表，但需要先创建分区
    // 这里先创建标准表，后续可以用 pg_partman 管理分区

    // 添加唯一约束
    await client.query(`
      DO $$ BEGIN
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.table_constraints
          WHERE table_name = 'klines' AND constraint_name = 'klines_symbol_interval_open_time_key'
        ) THEN
          ALTER TABLE klines ADD CONSTRAINT klines_symbol_interval_open_time_key
            UNIQUE(symbol, interval, open_time);
        END IF;
      END $$;
    `);

    // 创建复合索引（主要查询模式）
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_time
        ON klines(symbol, interval, open_time DESC);
    `);

    // 创建覆盖索引（避免回表，用于回测）
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_klines_covering
        ON klines(symbol, interval, open_time DESC)
        INCLUDE (open, high, low, close, volume);
    `);

    // 创建 24 小时行情表
    await client.query(`
      CREATE TABLE IF NOT EXISTS ticker_24hr (
        id BIGSERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        price_change NUMERIC(20, 8),
        price_change_percent NUMERIC(10, 4),
        weighted_avg_price NUMERIC(20, 8),
        prev_close_price NUMERIC(20, 8),
        last_price NUMERIC(20, 8),
        last_qty NUMERIC(20, 8),
        bid_price NUMERIC(20, 8),
        bid_qty NUMERIC(20, 8),
        ask_price NUMERIC(20, 8),
        ask_qty NUMERIC(20, 8),
        open_price NUMERIC(20, 8),
        high_price NUMERIC(20, 8),
        low_price NUMERIC(20, 8),
        volume NUMERIC(30, 8),
        quote_volume NUMERIC(30, 8),
        open_time TIMESTAMPTZ,
        close_time TIMESTAMPTZ,
        first_id BIGINT,
        last_id BIGINT,
        count INTEGER,
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, fetched_at)
      );
    `);

    // 创建订单簿表
    await client.query(`
      CREATE TABLE IF NOT EXISTS order_book (
        id BIGSERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        last_update_id BIGINT NOT NULL,
        bids JSONB NOT NULL,
        asks JSONB NOT NULL,
        fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
      );
    `);

    // 创建技术指标配置表
    await client.query(`
      CREATE TABLE IF NOT EXISTS indicator_configs (
        id SERIAL PRIMARY KEY,
        indicator_name VARCHAR(50) NOT NULL,
        parameters JSONB NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(indicator_name, parameters)
      );
    `);

    // 创建技术指标结果表
    await client.query(`
      CREATE TABLE IF NOT EXISTS indicator_values (
        id BIGSERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        interval VARCHAR(10) NOT NULL,
        open_time TIMESTAMPTZ NOT NULL,
        config_id INTEGER REFERENCES indicator_configs(id),
        indicator_value NUMERIC(30, 8),
        indicator_values JSONB,
        calculated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, interval, open_time, config_id)
      );
    `);

    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_indicator_symbol_interval_time
        ON indicator_values(symbol, interval, open_time DESC);
    `);

    console.log('✓ 数据库表结构初始化完成');

    // 保存数据库配置
    saveDatabaseConfig();

  } finally {
    client.release();
  }
}

/**
 * 保存数据库配置文件
 */
function saveDatabaseConfig() {
  const config = {
    ...dbConfig,
    password: '***' // 不保存真实密码
  };

  const configPath = path.join(__dirname, 'database-config.example.json');
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf-8');
  console.log('✓ 数据库配置示例已保存到 database-config.example.json');
}

/**
 * 插入 K 线数据
 */
async function insertKlines(symbol, interval, klines) {
  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    for (const k of klines) {
      await client.query(`
        INSERT INTO klines (
          symbol, interval, open_time, open, high, low, close, volume,
          close_time, quote_volume, trades, taker_buy_base_volume, taker_buy_quote_volume,
          is_complete, data_source
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        ON CONFLICT (symbol, interval, open_time) DO UPDATE SET
          open = EXCLUDED.open,
          high = EXCLUDED.high,
          low = EXCLUDED.low,
          close = EXCLUDED.close,
          volume = EXCLUDED.volume,
          quote_volume = EXCLUDED.quote_volume,
          trades = EXCLUDED.trades,
          taker_buy_base_volume = EXCLUDED.taker_buy_base_volume,
          taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
          is_complete = EXCLUDED.is_complete,
          data_source = EXCLUDED.data_source
      `, [
        symbol,
        interval,
        k.openTime,
        k.open,
        k.high,
        k.low,
        k.close,
        k.volume,
        k.closeTime,
        k.quoteVolume,
        k.trades,
        k.takerBuyBaseVolume,
        k.takerBuyQuoteVolume,
        k.isComplete,
        k.dataSource
      ]);
    }

    await client.query('COMMIT');
    console.log(`✓ 成功插入 ${klines.length} 条 ${symbol} ${interval} K线数据`);

  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

/**
 * 查询 K 线数据
 */
async function getKlines(symbol, interval, startTime, endTime, limit = 1000) {
  let query = `
    SELECT * FROM klines
    WHERE symbol = $1 AND interval = $2
  `;
  const params = [symbol, interval];

  if (startTime) {
    query += ` AND open_time >= $${params.length + 1}`;
    params.push(startTime);
  }
  if (endTime) {
    query += ` AND open_time <= $${params.length + 1}`;
    params.push(endTime);
  }

  query += ` ORDER BY open_time DESC LIMIT $${params.length + 1}`;
  params.push(limit);

  const result = await pool.query(query, params);
  return result.rows;
}

/**
 * 关闭连接池
 */
async function close() {
  await pool.end();
  console.log('✓ 数据库连接已关闭');
}

module.exports = {
  pool,
  initDatabase,
  insertKlines,
  getKlines,
  close
};
