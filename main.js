// @ts-check
const fs = require('fs');
const path = require('path');
const { MainClient } = require('./core');
const { initDatabase, insertKlines, close } = require('./database');
const { dbConfig, binanceConfig, appConfig } = require('./config/config.js');

/**
 * 币安量化交易数据收集主程序
 */

const client = new MainClient({
  api_key: binanceConfig.apiKey,
  api_secret: binanceConfig.apiSecret,
  testnet: binanceConfig.testnet
});

/**
 * 将币安 API 返回的 K 线数组转换为数据库格式
 */
function transformKline(kline) {
  return {
    openTime: new Date(parseInt(kline[0])),
    open: parseFloat(kline[1]),
    high: parseFloat(kline[2]),
    low: parseFloat(kline[3]),
    close: parseFloat(kline[4]),
    volume: parseFloat(kline[5]),
    closeTime: new Date(parseInt(kline[6])),
    quoteVolume: parseFloat(kline[7]),
    trades: parseInt(kline[8]),
    takerBuyBaseVolume: parseFloat(kline[9]),
    takerBuyQuoteVolume: parseFloat(kline[10]),
    dataSource: 'binance_api',
    isComplete: true
  };
}

/**
 * 保存 K 线数据到 JSON 文件
 */
function saveToJSON(klines, filename) {
  const dataDir = path.join(__dirname, 'data');
  if (!fs.existsSync(dataDir)) fs.mkdirSync(dataDir, { recursive: true });
  const filePath = path.join(dataDir, filename);
  fs.writeFileSync(filePath, JSON.stringify(klines, null, 2), 'utf-8');
  console.log(`  ✓ JSON 已保存: data/${filename}`);
}

async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  币安量化交易 - 数据收集系统');
  console.log('═══════════════════════════════════════════════\n');

  const config = {
    symbols: ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT'],
    intervals: ['1m', '5m', '15m', '1h', '4h', '1d'],
    limit: 1000,
    saveToFile: true,
    saveToDatabase: true
  };

  try {
    if (config.saveToDatabase) {
      await initDatabase();
    }

    for (const symbol of config.symbols) {
      for (const interval of config.intervals) {
        console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
        console.log(`处理 ${symbol} ${interval}`);
        console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);

        const raw = await client.getKlines(symbol, interval, { limit: config.limit });
        const klines = raw.map(transformKline);
        console.log(`  ✓ 获取到 ${klines.length} 条数据`);

        if (klines.length === 0) continue;

        if (config.saveToFile) {
          const timestamp = new Date().toISOString().slice(0, 10);
          saveToJSON(klines, `${symbol}-${interval}-${timestamp}.json`);
        }

        if (config.saveToDatabase) {
          await insertKlines(symbol, interval, klines);
        }

        // 避免请求过快
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }

    console.log('\n═══════════════════════════════════════════════');
    console.log('  数据收集完成！');
    console.log('═══════════════════════════════════════════════');

  } catch (error) {
    console.error('\n✗ 执行失败:', error.message);
    process.exit(1);
  } finally {
    if (config.saveToDatabase) {
      await close();
    }
  }
}

main();
