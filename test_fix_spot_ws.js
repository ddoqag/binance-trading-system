#!/usr/bin/env node
/**
 * 测试不同的测试网现货 WebSocket URL 构造
 */

const WebSocket = require('ws');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  测试网现货 WebSocket 修复尝试');
console.log('═══════════════════════════════════════════════\n');

async function testUrl(url, description) {
  console.log(`📋 测试: ${description}`);
  console.log(`   URL: ${url}`);

  return new Promise((resolve) => {
    let connected = false;
    let messageCount = 0;
    const timeout = setTimeout(() => {
      if (!connected) {
        console.log('❌ 连接超时');
        resolve(false);
      }
    }, 10000);

    try {
      const ws = new WebSocket(url);

      ws.on('open', () => {
        connected = true;
        console.log('✅ 连接成功');
      });

      ws.on('message', (data) => {
        messageCount++;
        try {
          const parsed = JSON.parse(data);
          if (parsed.e === 'kline' || parsed.e === '24hrMiniTicker') {
            console.log(`📨 收到消息: ${parsed.e} for ${parsed.s || 'unknown'}`);
          }
        } catch (e) {
          console.log(`📨 原始消息: ${data.toString().substring(0, 100)}`);
        }

        if (messageCount > 2) {
          clearTimeout(timeout);
          ws.close();
          console.log('✅ 测试成功');
          resolve(true);
        }
      });

      ws.on('error', (error) => {
        clearTimeout(timeout);
        console.log(`❌ 连接失败: ${error.message}`);
        resolve(false);
      });

      ws.on('close', (code, reason) => {
        clearTimeout(timeout);
        if (!connected || messageCount === 0) {
          console.log(`❌ 连接已关闭: code=${code}`);
          resolve(false);
        }
      });

    } catch (error) {
      clearTimeout(timeout);
      console.log(`❌ 异常: ${error.message}`);
      resolve(false);
    }
  });
}

async function main() {
  const symbol = 'btcusdt';
  const interval = '1m';

  // 测试不同的 URL 构造
  const testUrls = [
    {
      url: `wss://testnet.binance.vision/ws/${symbol}@kline_${interval}`,
      desc: '单个流 - @kline_1m'
    },
    {
      url: `wss://testnet.binance.vision/stream?streams=${symbol}@kline_${interval}`,
      desc: '多流格式 - streams 参数'
    },
    {
      url: 'wss://testnet.binance.vision/ws/btcusdt@miniTicker',
      desc: '迷你行情流 - @miniTicker'
    },
    {
      url: 'wss://testnet.binance.vision/ws/btcusdt@ticker',
      desc: '24h 行情流 - @ticker'
    },
    {
      url: 'wss://testnet.binance.vision/ws/btcusdt@trade',
      desc: '交易流 - @trade'
    },
    {
      url: 'wss://testnet.binance.vision/stream',
      desc: '基础流 - /stream'
    },
    {
      url: 'wss://testnet.binance.vision/ws',
      desc: '基础流 - /ws'
    },
  ];

  let successCount = 0;

  for (let i = 0; i < testUrls.length; i++) {
    const test = testUrls[i];
    console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${i+1}`);
    const result = await testUrl(test.url, test.desc);
    if (result) {
      successCount++;
    }
    // 稍微延迟以避免网络被封
    if (i < testUrls.length - 1) {
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }

  console.log('\n═══════════════════════════════════════════════');
  console.log(`  结果统计: ${successCount}/${testUrls.length} 成功`);
  console.log('═══════════════════════════════════════════════');

  if (successCount > 0) {
    console.log('\n🎉 找到有效的测试网现货 WebSocket URL！');
  } else {
    console.log('\n⚠️  未能找到有效的测试网现货 WebSocket URL');
    console.log('   建议:');
    console.log('   - 检查网络连接');
    console.log('   - 尝试不同的 VPN 服务器');
    console.log('   - 使用测试网期货 WebSocket（已确认工作）');
  }
}

main().catch(error => {
  console.error('❌ 程序错误:', error);
  process.exit(1);
});