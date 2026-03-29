#!/usr/bin/env node
/**
 * 网络诊断工具 - 测试 Binance WebSocket 连接
 */

const WebSocket = require('ws');
const https = require('https');

console.log('═══════════════════════════════════════════════');
console.log('  Binance 网络诊断工具');
console.log('═══════════════════════════════════════════════');

async function testHttps(url, name) {
  console.log(`\n🔍 测试 ${name} HTTPS 连接...`);
  return new Promise((resolve) => {
    const options = {
      hostname: new URL(url).hostname,
      port: 443,
      path: '/',
      method: 'GET',
      timeout: 10000
    };

    const req = https.request(options, (res) => {
      console.log(`✅ ${name} HTTPS 连接成功! (状态码: ${res.statusCode})`);
      resolve(true);
    });

    req.on('error', (error) => {
      console.log(`❌ ${name} HTTPS 连接失败:`, error.message);
      resolve(false);
    });

    req.on('timeout', () => {
      console.log(`❌ ${name} HTTPS 连接超时`);
      req.destroy();
      resolve(false);
    });

    req.setTimeout(10000);
    req.end();
  });
}

async function testWebSocket(url, name) {
  console.log(`\n🔌 测试 ${name} WebSocket 连接...`);
  console.log(`   URL: ${url}`);

  return new Promise((resolve) => {
    let connected = false;
    let timedOut = false;

    const ws = new WebSocket(url, {
      handshakeTimeout: 10000,
      followRedirects: true
    });

    const timeout = setTimeout(() => {
      timedOut = true;
      if (!connected) {
        console.log(`❌ ${name} WebSocket 连接超时`);
        ws.terminate();
        resolve(false);
      }
    }, 15000);

    ws.on('open', () => {
      connected = true;
      clearTimeout(timeout);
      console.log(`✅ ${name} WebSocket 连接成功!`);
      ws.close();
      resolve(true);
    });

    ws.on('error', (error) => {
      clearTimeout(timeout);
      if (!connected && !timedOut) {
        console.log(`❌ ${name} WebSocket 连接失败:`, error.message);
        resolve(false);
      }
    });

    ws.on('close', (code, reason) => {
      clearTimeout(timeout);
      if (connected) {
        console.log(`🔌 ${name} WebSocket 已关闭 (code: ${code})`);
      }
    });
  });
}

async function testWebSocketWithTopic(baseUrl, topic, name) {
  const url = `${baseUrl}/${topic}`;
  return await testWebSocket(url, `${name} (带主题)`);
}

async function main() {
  // 测试 HTTPS 连接
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  测试 1: HTTPS 连接测试');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  await testHttps('https://testnet.binance.vision', '测试网现货');
  await testHttps('https://stream.binancefuture.com', '测试网期货');
  await testHttps('https://api.binance.com', '生产网现货');

  // 测试 WebSocket 连接
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  测试 2: WebSocket 连接测试');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  // 测试不同的 URL
  const wsUrls = [
    { url: 'wss://testnet.binance.vision/ws', name: '测试网现货 (基础)' },
    { url: 'wss://testnet.binance.vision/stream', name: '测试网现货 (多流)' },
    { url: 'wss://stream.binancefuture.com/ws', name: '测试网期货 (基础)' },
  ];

  for (const { url, name } of wsUrls) {
    await testWebSocket(url, name);
  }

  // 测试带主题的 WebSocket
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('  测试 3: WebSocket 带主题连接');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

  await testWebSocketWithTopic(
    'wss://testnet.binance.vision/ws',
    'btcusdt@kline_1m',
    '测试网现货 K线'
  );

  await testWebSocketWithTopic(
    'wss://stream.binancefuture.com/ws',
    'btcusdt@kline_1m',
    '测试网期货 K线'
  );

  // 总结
  console.log('\n═══════════════════════════════════════════════');
  console.log('  诊断完成');
  console.log('═══════════════════════════════════════════════');
  console.log('');
  console.log('建议:');
  console.log('  - 如果 HTTPS 成功但 WebSocket 失败，检查网络防火墙');
  console.log('  - 确保 VPN 完全连接且没有 DNS 泄露');
  console.log('  - 尝试切换 VPN 服务器或使用不同的 VPN 协议');
  console.log('  - 检查本地防火墙设置，确保 9443/80/443 端口开放');
  console.log('');
}

main().catch(console.error);
