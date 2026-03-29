#!/usr/bin/env node
/**
 * 简化版 Node.js 实盘交易示例 - 仅 REST API
 */

const { MainClient } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  简化版 Node.js 实盘交易示例');
console.log('  (仅 REST API)');
console.log('═══════════════════════════════════════════════\n');

async function main() {
  try {
    // 配置
    const symbol = 'BTCUSDT';
    const interval = '1h';

    // 1. 初始化 REST API 客户端
    console.log('🧪 步骤1: 初始化 REST API 客户端');
    const client = new MainClient({
      testnet: true,
      api_key: process.env.BINANCE_API_KEY,
      api_secret: process.env.BINANCE_API_SECRET
    });
    console.log('✅ 客户端初始化成功\n');

    // 2. 获取交易所信息
    console.log('📋 步骤2: 获取交易所信息');
    const exchangeInfo = await client.getExchangeInfo();
    console.log(`✅ 成功 - 交易对数量: ${exchangeInfo.symbols.length}`);
    const btcSymbol = exchangeInfo.symbols.find(s => s.symbol === symbol);
    if (btcSymbol) {
      console.log(`   ${symbol} 状态: ${btcSymbol.status}`);
      console.log(`   价格精度: ${btcSymbol.quotePrecision}`);
      console.log(`   数量精度: ${btcSymbol.baseAssetPrecision}\n`);
    }

    // 3. 获取当前价格和市场数据
    console.log('📈 步骤3: 获取市场数据');
    const [price, ticker24h, orderBook] = await Promise.all([
      client.getPrice(symbol),
      client.getTicker24hr(symbol),
      client.getOrderBook(symbol, 10)
    ]);

    console.log(`✅ 当前价格: ${price.price} USDT`);
    console.log(`✅ 24h 涨跌幅: ${ticker24h.priceChangePercent}%`);
    console.log(`✅ 24h 成交量: ${ticker24h.volume} BTC`);
    console.log(`✅ 最佳买价: ${orderBook.bids[0][0]} @ ${orderBook.bids[0][1]}`);
    console.log(`✅ 最佳卖价: ${orderBook.asks[0][0]} @ ${orderBook.asks[0][1]}\n`);

    // 4. 获取 K 线数据
    console.log('📊 步骤4: 获取 K 线数据');
    const klines = await client.getKlines(symbol, interval, { limit: 10 });
    console.log(`✅ 成功 - 获取了 ${klines.length} 条 K 线`);
    if (klines.length > 0) {
      const lastK = klines[klines.length - 1];
      console.log(`   最后 K 线: O:${lastK[1]} H:${lastK[2]} L:${lastK[3]} C:${lastK[4]}`);
      console.log(`   时间: ${new Date(parseInt(lastK[0])).toISOString()}\n`);
    }

    // 5. 时间同步
    console.log('⏱️ 步骤5: 时间同步检查');
    const serverTime = await client.getServerTime();
    const localTime = Date.now();
    const timeOffset = client.getTimeOffset();
    console.log(`✅ 服务器时间: ${new Date(serverTime).toISOString()}`);
    console.log(`✅ 本地时间: ${new Date(localTime).toISOString()}`);
    console.log(`✅ 时间偏移: ${timeOffset}ms\n`);

    // 6. API 限流状态
    console.log('📊 步骤6: API 限流状态');
    const rateLimits = client.getRateLimitStates();
    console.log(`✅ 最后更新: ${new Date(rateLimits.lastUpdated).toISOString()}`);
    console.log(`✅ x-mbx-used-weight: ${rateLimits['x-mbx-used-weight']}\n`);

    // 7. 简单策略分析
    console.log('🎯 步骤7: 简单策略分析');
    const trend = await calculateTrend(klines);
    const levels = await checkSupportResistance(klines);
    const risk = assessRisk(klines, trend);

    console.log(`✅ 趋势分析: ${trend.direction} (置信度: ${trend.confidence.toFixed(2)})`);
    console.log(`✅ 支撑位: ${levels.support.toFixed(2)}, 阻力位: ${levels.resistance.toFixed(2)}`);
    console.log(`✅ 风险评估: ${risk.level}, 建议: ${risk.recommendation}\n`);

    // 8. 实盘交易建议
    console.log('📝 步骤8: 实盘交易建议');
    console.log('   1. 使用 MainClient 进行订单管理');
    console.log('   2. 使用 USDMClient 进行期货交易');
    console.log('   3. 使用 CoinMClient 进行币本位期货');
    console.log('   4. 集成到现有策略系统');
    console.log('   5. 参考 TIAGOSIEBLER_BINANCE_OPTIMIZATION_GUIDE.md 详细文档\n');

    console.log('═══════════════════════════════════════════════');
    console.log('  ✅ 示例运行成功完成！');
    console.log('═══════════════════════════════════════════════');

  } catch (error) {
    console.error('❌ 错误:');
    if (error.response) {
      console.error(`HTTP ${error.response.status}:`, error.response.data?.msg || error.response.data);
    } else {
      console.error(error.message);
    }
    process.exit(1);
  }
}

// 简单策略函数
async function calculateTrend(klines) {
  const closes = klines.map(k => parseFloat(k[4]));
  const returns = [];

  for (let i = 1; i < closes.length; i++) {
    returns.push((closes[i] - closes[i - 1]) / closes[i - 1]);
  }

  const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
  const volatility = Math.sqrt(returns.reduce((a, b) => a + Math.pow(b - avgReturn, 2), 0) / returns.length);

  const direction = avgReturn > 0 ? '上涨' : '下跌';
  const confidence = volatility > 0.02 ? 0.6 : 0.8;

  return {
    direction,
    confidence,
    avgReturn,
    volatility
  };
}

async function checkSupportResistance(klines) {
  const closes = klines.map(k => parseFloat(k[4]));
  const minPrice = Math.min(...closes);
  const maxPrice = Math.max(...closes);
  const range = maxPrice - minPrice;

  const support = minPrice + range * 0.2;
  const resistance = maxPrice - range * 0.2;

  return {
    support,
    resistance,
    min: minPrice,
    max: maxPrice
  };
}

function assessRisk(klines, trend) {
  const closes = klines.map(k => parseFloat(k[4]));
  const lastPrice = closes[closes.length - 1];
  const previousPrice = closes[closes.length - 2];

  const changePercent = ((lastPrice - previousPrice) / previousPrice) * 100;
  const highVolatility = Math.abs(changePercent) > 2;

  if (highVolatility || trend.confidence < 0.7) {
    return {
      level: '高风险',
      recommendation: '等待更好的进场时机'
    };
  } else if (trend.confidence > 0.8 && trend.direction === '上涨') {
    return {
      level: '低风险',
      recommendation: '可以考虑做多'
    };
  } else {
    return {
      level: '中风险',
      recommendation: '观望或小仓位'
    };
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error('❌ 程序错误:', error);
    process.exit(1);
  });
}
