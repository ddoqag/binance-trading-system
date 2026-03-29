#!/usr/bin/env node
/**
 * Redis 集成示例 - 展示如何在量化交易系统中使用 Redis
 */

const { RedisManager } = require('./redis_manager');

console.log('==========================================');
console.log('Redis 集成到量化交易系统示例');
console.log('==========================================\n');

async function main() {
    const manager = new RedisManager();

    // 1. 连接 Redis
    console.log('步骤 1: 连接 Redis...');
    const connected = await manager.connect();
    if (!connected) {
        console.error('❌ 连接失败');
        process.exit(1);
    }
    console.log('✅ 连接成功\n');

    // 2. 显示 Redis 信息
    const info = await manager.getInfo();
    if (info) {
        console.log('步骤 2: Redis 服务器信息');
        console.log(`  版本: ${info.Server?.redis_version}`);
        console.log(`  运行模式: ${info.Server?.redis_mode}`);
        console.log(`  内存使用: ${info.Memory?.used_memory_human}`);
        console.log(`  峰值内存: ${info.Memory?.used_memory_peak_human}`);
        console.log(`  连接数: ${info.Clients?.connected_clients}`);
        console.log('');
    }

    // 3. 模拟市场数据缓存
    console.log('步骤 3: 市场数据缓存示例');
    const symbol = 'BTCUSDT';
    const interval = '1h';
    const timestamp = Date.now();

    await manager.cacheKline(symbol, interval, timestamp, {
        open: '70000',
        high: '71500',
        low: '69200',
        close: '70800',
        volume: '1250',
        quoteAssetVolume: '88250000',
        tradeCount: '8900',
        closeTime: (timestamp + 3600000).toString()
    });
    console.log(`  ✅ 缓存 K 线数据: ${symbol} ${interval}`);

    const cachedKline = await manager.getCachedKline(symbol, interval, timestamp);
    console.log(`  ✅ 读取缓存: ${JSON.stringify(cachedKline).substring(0, 60)}...`);
    console.log('');

    // 4. 策略信号缓存
    console.log('步骤 4: 策略信号缓存示例');
    const strategies = ['DualMA', 'RSI', 'MLP'];

    for (const strategy of strategies) {
        await manager.cacheSignal(strategy, symbol, {
            signal: Math.random() > 0.5 ? 'BUY' : 'SELL',
            price: '70800',
            confidence: (0.7 + Math.random() * 0.3).toFixed(2),
            timestamp: Date.now()
        });
        console.log(`  ✅ 缓存策略信号: ${strategy}`);
    }

    const latestSignal = await manager.getSignal('DualMA', symbol);
    console.log(`  ✅ 读取信号: ${JSON.stringify(latestSignal)}`);
    console.log('');

    // 5. 熔断机制测试
    console.log('步骤 5: 熔断机制示例');
    const source = 'binance_api';

    for (let i = 1; i <= 7; i++) {
        const count = await manager.incrementErrorCount(source);
        const tripped = await manager.checkCircuitBreaker(source, 5);

        if (tripped) {
            console.log(`  ⚠️  错误计数: ${count} | 熔断器已触发！`);
        } else {
            console.log(`  ✓ 错误计数: ${count} | 正常`);
        }
    }
    console.log('');

    // 6. 统计数据缓存
    console.log('步骤 6: 统计数据缓存示例');
    await manager.cacheStats('stats:daily:pnl', '+1250.50');
    await manager.cacheStats('stats:daily:trades', '15');
    await manager.cacheStats('stats:daily:winrate', '66.67');
    console.log('  ✅ 缓存每日统计数据');

    const pnl = await manager.getStats('stats:daily:pnl');
    const trades = await manager.getStats('stats:daily:trades');
    const winrate = await manager.getStats('stats:daily:winrate');
    console.log(`  ✅ 读取统计: PNL=${pnl}, 交易次数=${trades}, 胜率=${winrate}%`);
    console.log('');

    // 7. 订单状态跟踪
    console.log('步骤 7: 订单状态跟踪示例');
    const orderId = 'ORD-' + Date.now();

    await manager.updateOrderStatus(orderId, 'PENDING');
    console.log(`  订单 ${orderId}: PENDING`);

    await new Promise(r => setTimeout(r, 100));
    await manager.updateOrderStatus(orderId, 'EXECUTING');
    console.log(`  订单 ${orderId}: EXECUTING`);

    await new Promise(r => setTimeout(r, 100));
    await manager.updateOrderStatus(orderId, 'FILLED');
    console.log(`  订单 ${orderId}: FILLED`);

    const finalStatus = await manager.getOrderStatus(orderId);
    console.log(`  ✅ 订单最终状态: ${finalStatus}`);
    console.log('');

    // 清理和断开
    console.log('步骤 8: 清理并断开连接');
    await manager.disconnect();
    console.log('✅ 已断开连接\n');

    console.log('==========================================');
    console.log('示例完成！');
    console.log('==========================================');
    console.log('\n可用功能:');
    console.log('  - cacheKline/getCachedKline: K线数据缓存');
    console.log('  - cacheSignal/getSignal: 策略信号缓存');
    console.log('  - updateOrderStatus/getOrderStatus: 订单状态跟踪');
    console.log('  - cacheStats/getStats: 统计数据缓存');
    console.log('  - incrementErrorCount/checkCircuitBreaker: 熔断机制');
}

main().catch(console.error);
