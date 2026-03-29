#!/usr/bin/env node
/**
 * Node.js 实盘交易示例 - 使用优化后的API客户端架构
 * 使用新的 Core API 客户端
 */

const { MainClient, WebsocketClient, WsKey } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  Node.js 实盘交易示例 - 优化后架构');
console.log('═══════════════════════════════════════════════');

async function realTradingExample() {
  console.log('\n📚 项目架构说明:');
  console.log('   - 使用新的模块化 REST API 客户端');
  console.log('   - 智能 WebSocket 连接管理');
  console.log('   - 自动重连和心跳管理');
  console.log('   - 时间同步和 API 限流跟踪');

  // 配置
  const symbol = 'BTCUSDT';
  const interval = '1h';

  // 1. 初始化 REST API 客户端
  console.log('\n🧪 测试1: REST API 客户端初始化');
  const client = new MainClient({
    testnet: true,  // 测试网模式（安全）
    api_key: process.env.BINANCE_API_KEY,
    api_secret: process.env.BINANCE_API_SECRET
  });

  // 2. 获取交易所信息
  console.log('\n📋 测试2: 获取交易所信息');
  const exchangeInfo = await client.getExchangeInfo();
  console.log(`✅ 成功 - 交易对数量: ${exchangeInfo.symbols.length}`);
  const btcSymbol = exchangeInfo.symbols.find(s => s.symbol === symbol);
  if (btcSymbol) {
    console.log(`   ${symbol} 状态: ${btcSymbol.status}`);
    console.log(`   价格精度: ${btcSymbol.quotePrecision}`);
    console.log(`   数量精度: ${btcSymbol.baseAssetPrecision}`);
  }

  // 3. 获取当前价格和市场数据
  console.log('\n📈 测试3: 获取市场数据');
  const [price, ticker24h, orderBook] = await Promise.all([
    client.getPrice(symbol),
    client.getTicker24hr(symbol),
    client.getOrderBook(symbol, 10)
  ]);

  console.log(`✅ 当前价格: ${price.price} USDT`);
  console.log(`✅ 24h 涨跌幅: ${ticker24h.priceChangePercent}%`);
  console.log(`✅ 24h 成交量: ${ticker24h.volume} ${symbol.split('USDT')[0]}`);
  console.log(`✅ 最佳买价: ${orderBook.bids[0][0]} @ ${orderBook.bids[0][1]}`);
  console.log(`✅ 最佳卖价: ${orderBook.asks[0][0]} @ ${orderBook.asks[0][1]}`);

  // 4. 获取 K 线数据
  console.log('\n📊 测试4: 获取 K 线数据');
  const klines = await client.getKlines(symbol, interval, { limit: 10 });
  console.log(`✅ 成功 - 获取了 ${klines.length} 条 K 线`);
  if (klines.length > 0) {
    const lastK = klines[klines.length - 1];
    console.log(`   最后 K 线: O:${lastK[1]} H:${lastK[2]} L:${lastK[3]} C:${lastK[4]}`);
    console.log(`   时间: ${new Date(parseInt(lastK[0])).toISOString()}`);
  }

  // 5. WebSocket 连接演示
  console.log('\n🔌 测试5: WebSocket 连接（模拟）');
  const wsClient = new WebsocketClient({
    testnet: false,
    api_key: process.env.BINANCE_API_KEY,
    api_secret: process.env.BINANCE_API_SECRET
  });

  // 监听事件
  wsClient.on('open', ({ wsKey }) => {
    console.log(`✅ WebSocket 已连接: ${wsKey}`);
  });

  wsClient.on('formattedMessage', (data) => {
    if (data.e === 'kline' && data.s === symbol) {
      const k = data.k;
      console.log(`📊 K线更新: ${data.s} ${k.i} - O:${k.o} H:${k.h} L:${k.l} C:${k.c}`);
    } else if (data.e === '24hrMiniTicker' && data.s === symbol) {
      const pct = ((parseFloat(data.c) - parseFloat(data.o)) / parseFloat(data.o) * 100).toFixed(2);
      console.log(`📈 24h行情: ${data.s} - ${data.c} (${pct}%)`);
    }
  });

  wsClient.on('exception', ({ wsKey, error }) => {
    console.error(`❌ WebSocket 错误: ${wsKey} - ${error.message}`);
  });

  wsClient.on('close', ({ wsKey, code, reason }) => {
    console.log(`🔌 WebSocket 已关闭: ${wsKey}, code=${code}`);
  });

  // 订阅实时数据（容错处理）
  console.log('📋 订阅实时 K 线和行情数据');
  try {
    await wsClient.subscribeKline(symbol, interval, WsKey.MAIN_PUBLIC);
    await wsClient.subscribeMiniTicker(symbol, WsKey.MAIN_PUBLIC);

    // 等待几秒钟接收数据
    console.log('⏳ 等待 3 秒钟接收数据...');
    await new Promise(resolve => setTimeout(resolve, 3000));

    // 关闭 WebSocket 连接
    console.log('🔌 关闭 WebSocket 连接');
    await wsClient.close(WsKey.MAIN_PUBLIC);
  } catch (error) {
    console.log('⚠️  WebSocket 连接超时，继续执行其他功能');
  }

  // 6. 策略执行架构
  console.log('\n🎯 测试6: 策略执行架构');

  // 简单策略: 计算趋势
  const trend = await calculateTrend(klines);
  console.log(`✅ 趋势分析: ${trend.direction} (置信度: ${trend.confidence.toFixed(2)})`);

  // 简单策略: 检查支撑阻力
  const levels = await checkSupportResistance(klines);
  console.log(`✅ 支撑位: ${levels.support.toFixed(2)}, 阻力位: ${levels.resistance.toFixed(2)}`);

  // 简单策略: 风险管理
  const risk = assessRisk(klines, trend);
  console.log(`✅ 风险评估: ${risk.level}, 建议: ${risk.recommendation}`);

  // 7. 实盘交易建议
  console.log('\n📝 实盘交易建议:');
  console.log('   1. 使用 MainClient 进行订单管理');
  console.log('   2. 使用 USDMClient 进行期货交易');
  console.log('   3. 使用 CoinMClient 进行币本位期货');
  console.log('   4. 使用 WebSocketClient 进行实时数据');
  console.log('   5. 集成到现有策略系统');
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

// 主函数
async function main() {
  try {
    // 检查 API 密钥
    if (!process.env.BINANCE_API_KEY || !process.env.BINANCE_API_SECRET) {
      console.error('❌ 错误: 缺少 API 密钥');
      console.log('请在 .env 文件中配置:');
      console.log('BINANCE_API_KEY=your_api_key');
      console.log('BINANCE_API_SECRET=your_api_secret');
      console.log('');
      console.log('或者使用环境变量:');
      console.log('export BINANCE_API_KEY=your_api_key');
      console.log('export BINANCE_API_SECRET=your_api_secret');
      process.exit(1);
    }

    // 确认实盘交易
    console.log('⚠️  实盘交易警告');
    console.log('   此脚本使用生产网模式');
    console.log('   请确保您已了解风险');

    const readline = require('readline');
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });

    await new Promise((resolve) => {
      rl.question('确认您要使用实盘交易? (输入 YES 确认): ', (answer) => {
        if (answer.toUpperCase() !== 'YES') {
          console.log('❌ 已取消');
          process.exit(0);
        }
        resolve();
      });
    });

    rl.close();

    // 执行示例
    await realTradingExample();

    console.log('\n✅ 测试完成');

  } catch (error) {
    console.error('❌ 错误:');
    if (error.response) {
      console.log(`HTTP ${error.response.status}: ${error.response.data?.msg || error.response.data}`);
    } else {
      console.log(error.message);
    }
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error('❌ 程序错误:', error);
    process.exit(1);
  });
}

module.exports = realTradingExample;