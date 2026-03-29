// @ts-check
const { Pool } = require('pg');

const dbConfig = {
  host: 'localhost',
  port: 5432,
  database: 'binance',
  user: 'postgres',
  password: '362232'
};

const pool = new Pool(dbConfig);

/**
 * 迁移技术指标表为宽表结构（每个指标一列）
 * 这样查询性能更好，适合机器学习特征提取
 */
async function migrateIndicatorTable() {
  console.log('正在迁移技术指标表结构...');

  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    // 检查旧表是否存在
    const checkOld = await client.query(`
      SELECT 1 FROM information_schema.tables
      WHERE table_name = 'technical_indicators'
    `);

    if (checkOld.rows.length > 0) {
      // 重命名旧表作为备份
      await client.query(`
        ALTER TABLE technical_indicators RENAME TO technical_indicators_old_kv;
      `);
      console.log('✓ 旧 KV 表已重命名为 technical_indicators_old_kv');
    }

    // 创建新的宽表（每个指标一列）
    await client.query(`
      CREATE TABLE IF NOT EXISTS technical_indicators (
        id BIGSERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        interval VARCHAR(10) NOT NULL,
        open_time TIMESTAMPTZ NOT NULL,

        -- 移动平均线
        ma7 NUMERIC(20, 8),
        ma25 NUMERIC(20, 8),
        ma99 NUMERIC(20, 8),

        -- RSI
        rsi14 NUMERIC(10, 4),

        -- MACD
        macd NUMERIC(20, 8),
        macd_signal NUMERIC(20, 8),
        macd_histogram NUMERIC(20, 8),

        -- 布林带
        bb_upper NUMERIC(20, 8),
        bb_middle NUMERIC(20, 8),
        bb_lower NUMERIC(20, 8),

        -- OBV
        obv NUMERIC(30, 8),

        -- 元数据
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(symbol, interval, open_time)
      );
    `);

    // 创建索引
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_tech_indicators_symbol_interval
      ON technical_indicators(symbol, interval, open_time DESC);
    `);

    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_tech_indicators_open_time
      ON technical_indicators(open_time DESC);
    `);

    await client.query('COMMIT');

    console.log('✓ 技术指标宽表创建成功！');
    console.log('\n表结构:');
    console.log('  - 移动平均线: ma7, ma25, ma99');
    console.log('  - RSI: rsi14');
    console.log('  - MACD: macd, macd_signal, macd_histogram');
    console.log('  - Bollinger Bands: bb_upper, bb_middle, bb_lower');
    console.log('  - OBV: obv');

  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  迁移技术指标表为宽表结构');
  console.log('═══════════════════════════════════════════════\n');

  try {
    await migrateIndicatorTable();
    console.log('\n✓ 迁移完成！');
  } catch (error) {
    console.error('\n✗ 迁移失败:', error.message);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

main();
