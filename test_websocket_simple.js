/**
 * WebSocket功能测试 - 使用实际主题测试连接
 */

const { WebsocketClient, WsKey } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  WebSocket功能测试');
console.log('═══════════════════════════════════════════════');

async function testWebSocketWithTopic() {
  console.log('\n🧪 测试: WebSocket连接（带主题）');
  console.log('─────────────────────────────────────────────');

  const wsClient = new WebsocketClient({
    testnet: true,
    pingInterval: 10000,
    pongTimeout: 5000,
    reconnectTimeout: 1000
  });

  // 设置事件监听器
  wsClient.on('open', ({ wsKey }) => {
    console.log(`✅ WebSocket已打开: ${wsKey}`);
  });

  wsClient.on('message', (data) => {
    console.log('📨 收到原始消息');
  });

  wsClient.on('formattedMessage', (data) => {
    if (data.e === 'kline') {
      console.log(`📊 K线更新: ${data.s} ${data.k.i} - O:${data.k.o} H:${data.k.h} L:${data.k.l} C:${data.k.c}`);
    } else if (data.e === '24hrMiniTicker') {
      console.log(`📈 24h行情: ${data.s} - ${data.c} (${data.P}%)`);
    } else {
      console.log('📋 格式化消息:', data);
    }
  });

  wsClient.on('close', ({ wsKey, code, reason }) => {
    console.log(`🔌 WebSocket已关闭: ${wsKey}, code=${code}, reason=${reason}`);
  });

  wsClient.on('reconnecting', ({ wsKey }) => {
    console.log(`🔄 正在重连: ${wsKey}`);
  });

  wsClient.on('reconnected', ({ wsKey }) => {
    console.log(`✅ 已重连: ${wsKey}`);
  });

  wsClient.on('exception', ({ wsKey, error }) => {
    console.log(`❌ 异常: ${wsKey}`, error);
  });

  try {
    // 测试1: 订阅K线
    console.log('\n📋 测试1: 订阅BTCUSDT 1分钟K线');
    await wsClient.subscribeKline('BTCUSDT', '1m', WsKey.MAIN_PUBLIC);
    console.log('✅ 订阅请求已发送');

    // 等待5秒接收数据
    console.log('\n⏳ 等待5秒接收数据...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    // 测试2: 订阅miniTicker
    console.log('\n📋 测试2: 订阅BTCUSDT迷你行情');
    await wsClient.subscribeMiniTicker('BTCUSDT', WsKey.MAIN_PUBLIC);
    console.log('✅ 订阅请求已发送');

    // 等待5秒接收数据
    console.log('\n⏳ 等待5秒接收数据...');
    await new Promise(resolve => setTimeout(resolve, 5000));

    console.log('\n✅ WebSocket功能测试完成!');

    // 优雅关闭
    console.log('\n🔌 关闭连接...');
    await wsClient.close(WsKey.MAIN_PUBLIC);
    console.log('✅ 连接已关闭');

  } catch (error) {
    console.error('❌ 测试失败:', error);
  }
}

// 运行测试
testWebSocketWithTopic().catch(error => {
  console.error('❌ 测试执行失败:', error);
  process.exit(1);
});

// 30秒后强制退出
setTimeout(() => {
  console.log('\n⏰ 测试超时，强制退出');
  process.exit(0);
}, 30000);