#!/usr/bin/env node

const { MainClient } = require('./core');
const { initDatabase, insertKlines, getKlines, close } = require('./database');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  从币安API获取真实K线数据');
console.log('═══════════════════════════════════════════════');

// 配置
const SYMBOL = process.env.DEFAULT_SYMBOL || 'BTCUSDT';
const INTERVAL = process.env.DEFAULT_INTERVAL || '1h';
const LIMIT = 1000; // 币安API限制最多1000条

// 币安API客户端
const client = new MainClient({
  api_key: process.env.BINANCE_API_KEY,
  api_secret: process.env.BINANCE_API_SECRET,
  testnet: process.env.USE_TESTNET === 'true'
});

// 将币安API返回的K线数据转换为数据库格式
function transformBinanceKline(kline) {
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

async function fetchAndSaveData() {
  try {
    // 初始化数据库
    console.log('正在初始化数据库...');
    await initDatabase();

    // 获取最新数据的时间范围
    const latestData = await getKlines(SYMBOL, INTERVAL, null, null, 1);
    let startTime = null;

    if (latestData.length > 0) {
      startTime = new Date(latestData[0].open_time.getTime() + 60000); // 下一分钟
      console.log(`数据库最新数据时间: ${latestData[0].open_time}`);
      console.log(`将获取从: ${startTime} 开始的数据`);
    } else {
      console.log('数据库中没有数据，将获取最近的K线数据');
    }

    // 从币安API获取数据
    console.log(`正在获取 ${SYMBOL} ${INTERVAL} 数据...`);
    const options = {};
    if (startTime) {
      options.startTime = startTime.getTime();
    }

    const klines = await client.getKlines(SYMBOL, INTERVAL, {
      limit: LIMIT,
      ...options
    });

    if (klines.length === 0) {
      console.log('✓ 没有新数据需要获取');
    } else {
      console.log(`✓ 获取到 ${klines.length} 条新数据`);

      // 转换数据格式
      const transformedKlines = klines.map(transformBinanceKline);

      // 保存到数据库
      await insertKlines(SYMBOL, INTERVAL, transformedKlines);
    }

    // 验证数据
    const verifyData = await getKlines(SYMBOL, INTERVAL, null, null, 5);
    console.log(`\n✓ 数据库中最新的5条数据: ${verifyData.length} 条`);
    verifyData.forEach((k, i) => {
      console.log(`  ${i+1}. ${k.open_time} - ${k.close}`);
    });

  } catch (error) {
    console.error('❌ 错误:', error.message);
    if (error.response) {
      console.error('响应状态:', error.response.status);
      console.error('响应数据:', error.response.data);
    }
  } finally {
    await close();
  }
}

// 执行
fetchAndSaveData();
