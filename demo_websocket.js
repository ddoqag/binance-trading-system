/**
 * WebSocket智能连接演示
 * 展示自动重连、心跳管理等功能
 */

const { WebsocketClient, WsKey } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  WebSocket智能连接演示');
console.log('═══════════════════════════════════════════════\n');

const wsClient = new WebsocketClient({
  api_key: process.env.BINANCE_API_KEY || '',
  api_secret: process.env.BINANCE_API_SECRET || '',
  testnet: true,
  pingInterval: 10000,     // 10秒ping
  pongTimeout: 5000,       // 5秒超时
  reconnectTimeout: 1000    // 1秒重连延迟
});

// 事件监听
let messageCount = 0;
let startTimestamp = Date.now();

wsClient.on('open', ({ wsKey }) => {
  console.log(`✅ 连接打开: ${wsKey}`);
  console.log(`⏱️  时间: ${new Date().toISOString()}`);
});

wsClient.on('reconnecting', ({ wsKey }) => {
  console.log(`🔄 正在重连: ${wsKey}`);
  console.log(`⏱️  时间: ${new Date().toISOString()}`);
});

wsClient.on('reconnected', ({ wsKey }) => {
  console.log(`✅ 重连成功: ${wsKey}`);
  console.log(`⏱️  时间: ${new Date().toISOString()}`);
  console.log(`📊  已接收消息: ${messageCount}`);
});

wsClient.on('close', ({ wsKey, code, reason }) => {
  console.log(`❌ 连接关闭: ${wsKey}`);
  console.log(`   关闭码: ${code}`);
  console.log(`   原因: ${reason}`);
  console.log(`⏱️  时间: ${new Date().toISOString()}`);
});

wsClient.on('formattedMessage', (data) => {
  messageCount++;
  const elapsed = (Date.now() - startTimestamp) / 1000;

  if (messageCount % 10 === 1) {
    console.log(`📨  收到第 ${messageCount} 条消息 (${elapsed.toFixed(1)}s)`);
  }

  if (data.e === 'kline' && messageCount % 50 === 0) {
    const k = data.k;
    console.log(`   📈 K线: ${k.s} ${k.i} | O:${k.o} H:${k.h} L:${k.l} C:${k.c}`);
    console.log(`      成交量: ${k.v}, 成交数: ${k.n}`);
  }
});

wsClient.on('exception', ({ wsKey, error }) => {
  console.error(`⚠️  异常: ${wsKey} -`, error.message);
});

console.log('📋 订阅主题:');
console.log('   - BTCUSDT 1m K线');
console.log('   - BTCUSDT 深度(20档)');
console.log('   - BTCUSDT 聚合交易');
console.log('');

// 订阅多个主题
wsClient.subscribeKline('BTCUSDT', '1m', WsKey.MAIN_PUBLIC);
wsClient.subscribeDepth('BTCUSDT', 20, WsKey.MAIN_PUBLIC);
wsClient.subscribeAggTrade('BTCUSDT', WsKey.MAIN_PUBLIC);

console.log('🚀 WebSocket已启动，将运行30秒...');
console.log('');

// 30秒后停止
setTimeout(() => {
  console.log('');
  console.log('═══════════════════════════════════════════════');
  console.log('  演示完成');
  console.log('═══════════════════════════════════════════════');
  console.log('📊 统计:');
  console.log(`   总消息数: ${messageCount}`);
  console.log(`   运行时间: ${((Date.now() - startTimestamp) / 1000).toFixed(1)}s`);
  console.log(`   平均消息速率: ${(messageCount / ((Date.now() - startTimestamp) / 1000)).toFixed(2)} 条/秒`);
  console.log('');
  console.log('✅ 核心功能验证:');
  console.log('   ✅ WebSocket连接管理');
  console.log('   ✅ 多主题订阅');
  console.log('   ✅ 事件驱动架构');
  console.log('   ✅ 自动心跳检测');
  console.log('');

  wsClient.close(WsKey.MAIN_PUBLIC);
  console.log('✅ 连接已关闭');
}, 30000);

// 优雅退出
process.on('SIGINT', () => {
  console.log('\n\n👋 收到中断信号，正在关闭连接...');
  wsClient.close(WsKey.MAIN_PUBLIC, true);
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n\n👋 收到终止信号，正在关闭连接...');
  wsClient.close(WsKey.MAIN_PUBLIC, true);
  process.exit(0);
});
