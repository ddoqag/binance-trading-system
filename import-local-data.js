const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  本地数据导入到 PostgreSQL 数据库');
console.log('═══════════════════════════════════════════════\n');

const pool = new Pool({
  host: process.env.DB_HOST || 'localhost',
  port: process.env.DB_PORT || 5432,
  database: process.env.DB_NAME || 'binance',
  user: process.env.DB_USER || 'postgres',
  password: process.env.DB_PASSWORD || ''
});

// 需要导入的数据文件
const FILES_TO_IMPORT = [
  { symbol: 'BTCUSDT', interval: '1h', file: 'BTCUSDT-1h-2026-03-20.json' },
  { symbol: 'BTCUSDT', interval: '15m', file: 'BTCUSDT-15m-2026-03-20.json' }
];

async function readJsonFile(filePath) {
  return new Promise((resolve, reject) => {
    fs.readFile(filePath, 'utf8', (err, data) => {
      if (err) reject(err);
      else resolve(JSON.parse(data));
    });
  });
}

async function importFile(symbol, interval, fileName) {
  const filePath = path.join(__dirname, 'data', fileName);
  console.log(`\n[1/2] 读取文件: ${fileName}`);

  let data;
  try {
    data = await readJsonFile(filePath);
    console.log(`✓ 读取成功: ${data.length} 条记录`);
  } catch (error) {
    console.error(`✗ 读取文件失败: ${error.message}`);
    return 0;
  }

  console.log(`[2/2] 导入到 klines 表...`);
  const klines = data.map(k => ({
    symbol,
    interval,
    open_time: new Date(k.openTime).toISOString(),
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close,
    volume: k.volume,
    close_time: new Date(k.closeTime).toISOString(),
    quote_volume: k.quoteVolume,
    trades: k.trades,
    taker_buy_base_volume: k.takerBuyBaseVolume,
    taker_buy_quote_volume: k.takerBuyQuoteVolume,
    data_source: 'local_file',
    is_complete: k.isComplete
  }));

  let importedCount = 0;
  let skippedCount = 0;

  for (let i = 0; i < klines.length; i++) {
    const kline = klines[i];

    try {
      // 检查是否已存在
      const result = await pool.query(`
        SELECT COUNT(*) FROM klines
        WHERE symbol = $1
          AND interval = $2
          AND open_time = $3
      `, [symbol, interval, kline.open_time]);

      if (result.rows[0].count == 0) {
        // 插入新数据
        await pool.query(`
          INSERT INTO klines (
            symbol, interval, open_time, open, high, low, close, volume,
            close_time, quote_volume, trades, taker_buy_base_volume,
            taker_buy_quote_volume, data_source, is_complete
          ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        `, [
          symbol, interval, kline.open_time, kline.open, kline.high, kline.low,
          kline.close, kline.volume, kline.close_time, kline.quote_volume,
          kline.trades, kline.taker_buy_base_volume, kline.taker_buy_quote_volume,
          kline.data_source, kline.is_complete
        ]);
        importedCount++;
      } else {
        skippedCount++;
      }
    } catch (error) {
      console.error(`  行 ${i+1} 插入失败:`, error.message);
    }
  }

  console.log(`✓ 导入完成: ${importedCount} 条新增, ${skippedCount} 条已存在`);
  return importedCount;
}

async function main() {
  const startTime = Date.now();
  let totalImported = 0;

  for (const config of FILES_TO_IMPORT) {
    const imported = await importFile(config.symbol, config.interval, config.file);
    totalImported += imported;
  }

  const duration = (Date.now() - startTime) / 1000;

  console.log('\n═══════════════════════════════════════════════');
  console.log('  导入完成');
  console.log('═══════════════════════════════════════════════');
  console.log(`✓ 总导入记录: ${totalImported}`);
  console.log(`⏱️  耗时: ${duration.toFixed(2)} 秒`);

  await pool.end();
}

// 运行主函数
main().catch(error => {
  console.error('\n✗ 导入失败:', error);
  pool.end();
});
