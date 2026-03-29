#!/usr/bin/env node
/**
 * 修复版 WebSocket 测试 - 使用期货 WebSocket
 */

const { WebsocketClient, WsKey, USDMClient } = require('./core');
require('dotenv').config();

console.log('═══════════════════════════════════════════════');
console.log('  修复版 WebSocket 测试');
console.log('  (使用测试网期货)');
console.log('═══════════════════════════════════════════════\n');

async function main() {
  try {
    console.log('📋 测试1: USDM 期货 REST API');
    const client = new USDMClient({ testnet: true });
    const exchangeInfo = await client.getExchangeInfo();
    console.log(`✅ 期货交易所信息: ${exchangeInfo.symbols.length} 个合约\n`);

    console.log('📋 测试2: WebSocket 客户端初始化');
    const wsClient = new WebsocketClient({
      testnet: true,
      pingInterval: 15000,
      pongTimeout: 10000,
      reconnectTimeout: 2000
    });
    console.log('✅ WebSocket 客户端初始化成功\n');

    // 设置事件监听器
    let messageCount = 0;
    let connected = false;

    wsClient.on('open', ({ wsKey }) => {
      connected = true;
      console.log(`✅ WebSocket 已打开: ${wsKey}\n`);
    });

    wsClient.on('formattedMessage', (data) => {
      messageCount++;
      if (data.e === 'kline') {
        const k = data.k;
        console.log(`📊 K线更新 #${messageCount} - ${data.s} ${k.i}`);
        console.log(`   O:${k.o} H:${k.h} L:${k.l} C:${k.c}`);
        console.log(`   时间: ${new Date(parseInt(k.t)).toLocaleTimeString()}`);
      } else if (data.e === '24hrMiniTicker') {
        console.log(`📈 24h行情 #${messageCount} - ${data.s}: ${data.c} (${data.P}%)`);
      } else if (data.e === 'markPriceUpdate') {
        console.log(`💰 标记价格 #${messageCount} - ${data.s}: ${data.p}`);
      } else {
        console.log(`📋 消息 #${messageCount}:`, data.e || data);
      }
      console.log('');
    });

    wsClient.on('message', (data) => {
      // 只显示前几条原始消息
      if (messageCount <= 2) {
        try {
          const parsed = JSON.parse(data);
          console.log(`📨 原始消息 #${messageCount + 1}:`, parsed.e || Object.keys(parsed));
        } catch (e) {
          console.log(`📨 原始消息 #${messageCount + 1}:`, data.toString().substring(0, 100));
        }
      }
    });

    wsClient.on('close', ({ wsKey, code, reason }) => {
      console.log(`🔌 WebSocket 已关闭: ${wsKey}, code=${code}`);
    });

    wsClient.on('reconnecting', ({ wsKey }) => {
      console.log(`🔄 正在重连: ${wsKey}...`);
    });

    wsClient.on('reconnected', ({ wsKey }) => {
      console.log(`✅ 已重连: ${wsKey}`);
    });

    wsClient.on('exception', ({ wsKey, error }) => {
      console.log(`❌ 异常: ${wsKey} -`, error.message);
    });

    // 测试订阅期货 K 线
    console.log('📋 测试3: 订阅期货 BTCUSDT 1分钟 K线');
    await wsClient.subscribeFuturesKline('BTCUSDT', '1m', WsKey.USDM_PUBLIC);
    console.log('✅ 订阅请求已发送\n');

    // 等待数据
    console.log('⏳ 等待 10 秒接收数据... (按 Ctrl+C 停止)\n');
    const startTime = Date.now();

    const waitLoop = setInterval(() => {
      if (Date.now() - startTime > 10000) {
        clearInterval(waitLoop);
        finish();
      }
    }, 1000);

    async function finish() {
      console.log('\n📊 结果统计:');
      console.log(`   连接状态: ${connected ? '✅ 已连接' : '❌ 未连接'}`);
      console.log(`   接收消息: ${messageCount} 条`);
      console.log('');

      console.log('🔌 关闭 WebSocket 连接...');
      await wsClient.close(WsKey.USDM_PUBLIC);
      console.log('✅ 连接已关闭\n');

      console.log('═══════════════════════════════════════════════');
      console.log('  ✅ 测试完成');
      console.log('═══════════════════════════════════════════════');

      if (connected && messageCount > 0) {
        console.log('\n🎉 成功: WebSocket 连接正常并收到数据!');
      } else {
        console.log('\n⚠️  提示: 请检查网络连接或切换 VPN');
      }

      process.exit(0);
    }

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

process.on('SIGINT', () => {
  console.log('\n\n👋 用户中断，正在退出...');
  process.exit(0);
});

main().catch(console.error);
