/**
 * WebSocket调试脚本 - 直接测试连接
 */

const WebSocket = require('ws');

console.log('═══════════════════════════════════════════════');
console.log('  WebSocket调试');
console.log('═══════════════════════════════════════════════');

// 测试不同的URL
const testUrls = [
  {
    name: '测试网现货K线 (直接流)',
    url: 'wss://testnet.binance.vision/ws/btcusdt@kline_1m'
  },
  {
    name: '测试网现货迷你行情',
    url: 'wss://testnet.binance.vision/ws/btcusdt@miniTicker'
  },
  {
    name: '测试网现货多流',
    url: 'wss://testnet.binance.vision/stream?streams=btcusdt@kline_1m/btcusdt@miniTicker'
  }
];

async function testUrl(testConfig) {
  console.log(`\n🧪 测试: ${testConfig.name}`);
  console.log(`   URL: ${testConfig.url}`);
  console.log('─────────────────────────────────────────────');

  return new Promise((resolve) => {
    try {
      const ws = new WebSocket(testConfig.url);
      let messageCount = 0;
      let connected = false;
      const timeout = setTimeout(() => {
        if (!connected) {
          console.log('❌ 连接超时');
          ws.terminate();
          resolve(false);
        }
      }, 10000);

      ws.on('open', () => {
        console.log('✅ 连接成功!');
        connected = true;
      });

      ws.on('message', (data) => {
        messageCount++;
        if (messageCount <= 3) {
          try {
            const parsed = JSON.parse(data);
            console.log(`📨 消息 #${messageCount}:`, JSON.stringify(parsed, null, 2).substring(0, 300));
          } catch (e) {
            console.log(`📨 消息 #${messageCount}: ${data.toString().substring(0, 200)}`);
          }
        } else if (messageCount === 4) {
          console.log('📨 ... (更多消息已收到)');
        }
      });

      ws.on('error', (error) => {
        console.log('❌ 错误:', error.message);
      });

      ws.on('close', (code, reason) => {
        console.log(`🔌 连接关闭: code=${code}, reason=${reason}`);
        clearTimeout(timeout);
        resolve(connected);
      });

      // 5秒后关闭
      setTimeout(() => {
        if (ws.readyState === WebSocket.OPEN) {
          console.log('\n⏳ 5秒后关闭连接...');
          ws.close();
        }
      }, 5000);

    } catch (error) {
      console.log('❌ 异常:', error.message);
      resolve(false);
    }
  });
}

async function main() {
  for (const testConfig of testUrls) {
    await testUrl(testConfig);
  }
  console.log('\n═══════════════════════════════════════════════');
  console.log('  调试完成');
  console.log('═══════════════════════════════════════════════');
}

main().catch(console.error);