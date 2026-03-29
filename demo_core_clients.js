/**
 * 演示优化后的币安API客户端
 * 展示新架构的主要功能
 */

const { MainClient, WebsocketClient, WsKey } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  优化后的币安API客户端演示');
console.log('═══════════════════════════════════════════════');

// 配置
const config = {
  api_key: process.env.BINANCE_API_KEY || '',
  api_secret: process.env.BINANCE_API_SECRET || '',
  testnet: true
};

// 检查是否有API密钥
if (!config.api_key || !config.api_secret) {
  console.warn('⚠️  API密钥未配置，仅演示公开接口');
}

async function main() {
  try {
    console.log('\n1. 初始化REST API客户端');
    const restClient = new MainClient(config);
    console.log('✅ 成功');

    console.log('\n2. 获取服务器时间同步');
    const serverTime = await restClient.getServerTime();
    console.log('✅ 服务器时间:', new Date(serverTime));
    console.log('✅ 本地时间:', new Date());

    console.log('\n3. 获取市场数据（BTCUSDT 1h K线）');
    const klines = await restClient.getKlines('BTCUSDT', '1h', { limit: 10 });
    console.log('✅ 成功获取', klines.length, '条K线');
    const lastCandle = klines[klines.length - 1];
    console.log('✅ 最后K线: O', lastCandle[1], 'H', lastCandle[2], 'L', lastCandle[3], 'C', lastCandle[4]);

    console.log('\n4. 获取市场深度（BTCUSDT）');
    const orderBook = await restClient.getOrderBook('BTCUSDT', 10);
    console.log('✅ 买盘数量:', orderBook.bids.length, '卖盘数量:', orderBook.asks.length);
    console.log('✅ 最佳买入价:', orderBook.bids[0][0], '数量:', orderBook.bids[0][1]);
    console.log('✅ 最佳卖出价:', orderBook.asks[0][0], '数量:', orderBook.asks[0][1]);

    console.log('\n5. 获取当前价格');
    const ticker = await restClient.getPrice('BTCUSDT');
    console.log('✅ BTCUSDT价格:', ticker.price);

    console.log('\n6. 获取24小时行情');
    const dayTicker = await restClient.getTicker24hr('BTCUSDT');
    console.log('✅ 24h 开盘价:', dayTicker.openPrice);
    console.log('✅ 24h 最高价:', dayTicker.highPrice);
    console.log('✅ 24h 最低价:', dayTicker.lowPrice);
    console.log('✅ 24h 成交量:', dayTicker.volume);
    console.log('✅ 24h 涨跌幅:', dayTicker.priceChangePercent, '%');

    // 如果有API密钥，测试认证接口
    if (config.api_key && config.api_secret) {
      try {
        console.log('\n7. 获取账户信息（需要认证）');
        const account = await restClient.getAccount();
        console.log('✅ 账户状态:', account.updateTime ? '正常' : '异常');
        console.log('✅ 总资产:', account.balances.length, '种');
        const btcBalance = account.balances.find(b => b.asset === 'BTC');
        if (btcBalance) {
          console.log('✅ BTC余额:', btcBalance.free, '可用 +', btcBalance.locked, '冻结');
        }
      } catch (error) {
        console.warn('⚠️  账户信息获取失败:', error.message);
      }
    }

    // 启动WebSocket演示（后台运行）
    console.log('\n8. 启动WebSocket演示（5秒后停止）');
    const wsClient = new WebsocketClient({
      ...config,
      pingInterval: 10000,
      pongTimeout: 5000
    });

    // 事件监听
    wsClient.on('open', ({ wsKey }) => {
      console.log(`✅ WebSocket连接成功: ${wsKey}`);
    });

    wsClient.on('reconnected', ({ wsKey }) => {
      console.log(`🔄 WebSocket重连成功: ${wsKey}`);
    });

    wsClient.on('close', ({ wsKey, code, reason }) => {
      console.log(`❌ WebSocket断开连接: ${wsKey} - ${code} ${reason}`);
    });

    wsClient.on('formattedMessage', (data) => {
      if (data.e === 'kline') {
        const candle = data.k;
        console.log(`📈 K线更新: ${candle.s} ${candle.i} O:${candle.o} H:${candle.h} L:${candle.l} C:${candle.c}`);
      } else if (data.e === 'depthUpdate') {
        console.log(`📊 深度更新: ${data.s} - ${data.U} - ${data.u}`);
      } else if (data.e === 'aggTrade') {
        console.log(`💱 成交: ${data.s} ${data.p} ${data.q}`);
      }
    });

    wsClient.on('exception', ({ wsKey, error }) => {
      console.error(`⚠️ WebSocket错误: ${wsKey} -`, error);
    });

    // 订阅几个主题
    console.log('✅ 订阅BTCUSDT 1m K线');
    wsClient.subscribeKline('BTCUSDT', '1m', WsKey.MAIN_PUBLIC);

    console.log('✅ 订阅BTCUSDT深度');
    wsClient.subscribeDepth('BTCUSDT', 20, WsKey.MAIN_PUBLIC);

    console.log('✅ 订阅BTCUSDT成交');
    wsClient.subscribeAggTrade('BTCUSDT', WsKey.MAIN_PUBLIC);

    // 5秒后停止演示
    setTimeout(() => {
      console.log('\n⏱️  演示时间结束');
      wsClient.close(WsKey.MAIN_PUBLIC);
      console.log('✅ WebSocket连接已关闭');
    }, 5000);

  } catch (error) {
    console.error('\n❌ 演示执行失败:', error);
  }
}

// 执行演示
main().catch(error => {
  console.error('❌ 启动失败:', error);
  process.exit(1);
});
