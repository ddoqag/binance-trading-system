#!/usr/bin/env node
/**
 * Redis 管理器 - 用于量化交易系统
 */

const redis = require('redis');
require('dotenv').config();

console.log('==========================================');
console.log('Redis 管理器 - 量化交易系统');
console.log('==========================================');

// Redis 连接配置
const config = {
    socket: {
        host: process.env.REDIS_HOST || 'localhost',
        port: parseInt(process.env.REDIS_PORT || '6379'),
        connectTimeout: 5000,
        reconnectStrategy: (retries) => Math.min(retries * 50, 500)
    }
};

// Only add password if it's actually set
if (process.env.REDIS_PASSWORD && process.env.REDIS_PASSWORD.trim()) {
    config.password = process.env.REDIS_PASSWORD;
}

// Add database if specified
if (process.env.REDIS_DB) {
    config.database = parseInt(process.env.REDIS_DB);
}

class RedisManager {
    constructor() {
        this.client = null;
        this.connected = false;
    }

    // 连接到 Redis
    async connect() {
        try {
            console.log('连接到 Redis...');
            this.client = redis.createClient(config);

            this.client.on('error', (err) => {
                console.error('Redis 错误:', err);
                this.connected = false;
            });

            this.client.on('connect', () => {
                console.log('✅ Redis 已连接');
                this.connected = true;
            });

            this.client.on('reconnecting', () => {
                console.log('🔄 Redis 重连中...');
            });

            await this.client.connect();
            return true;

        } catch (error) {
            console.error('❌ Redis 连接失败:', error);
            return false;
        }
    }

    // 断开连接
    async disconnect() {
        if (this.client) {
            await this.client.quit();
            this.connected = false;
            console.log('Redis 已断开');
        }
    }

    // 缓存 K 线数据
    async cacheKline(symbol, interval, timestamp, data) {
        const key = `kline:${symbol}:${interval}:${timestamp}`;
        await this.client.hSet(key, data);
        await this.client.expire(key, 3600); // 1小时过期
    }

    // 获取缓存的 K 线数据
    async getCachedKline(symbol, interval, timestamp) {
        const key = `kline:${symbol}:${interval}:${timestamp}`;
        return await this.client.hGetAll(key);
    }

    // 缓存策略信号
    async cacheSignal(strategy, symbol, signal) {
        const key = `signal:${strategy}:${symbol}`;
        await this.client.setEx(key, 60, JSON.stringify(signal));
    }

    // 获取策略信号
    async getSignal(strategy, symbol) {
        const key = `signal:${strategy}:${symbol}`;
        const data = await this.client.get(key);
        return data ? JSON.parse(data) : null;
    }

    // 更新订单状态
    async updateOrderStatus(orderId, status) {
        const key = `order:${orderId}`;
        await this.client.hSet(key, 'status', status);
        await this.client.expire(key, 86400); // 24小时过期
    }

    // 获取订单状态
    async getOrderStatus(orderId) {
        const key = `order:${orderId}`;
        return await this.client.hGet(key, 'status');
    }

    // 缓存统计数据
    async cacheStats(key, value) {
        await this.client.setEx(key, 3600, value);
    }

    // 获取统计数据
    async getStats(key) {
        return await this.client.get(key);
    }

    // 增量错误计数
    async incrementErrorCount(source) {
        const key = `error:count:${source}`;
        const count = await this.client.incr(key);
        await this.client.expire(key, 60); // 1分钟过期
        return count;
    }

    // 检查熔断
    async checkCircuitBreaker(source, threshold = 5) {
        const key = `error:count:${source}`;
        const count = parseInt(await this.client.get(key) || '0');
        return count > threshold;
    }

    // 获取 Redis 信息
    async getInfo() {
        if (!this.connected) return null;

        try {
            const info = await this.client.info('server');
            const memInfo = await this.client.info('memory');
            const clientsInfo = await this.client.info('clients');

            const result = {};

            // 简单解析
            const parse = (str) => {
                const obj = {};
                str.split('\r\n').forEach(line => {
                    if (line && !line.startsWith('#')) {
                        const [k, v] = line.split(':');
                        if (k && v) obj[k.trim()] = v.trim();
                    }
                });
                return obj;
            };

            result.Server = parse(info);
            result.Memory = parse(memInfo);
            result.Clients = parse(clientsInfo);

            return result;
        } catch (error) {
            console.error('获取 Redis 信息失败:', error);
            return null;
        }
    }
}

// 使用示例
async function main() {
    const manager = new RedisManager();

    const connected = await manager.connect();
    if (!connected) {
        console.log('💡 提示: 请确认 WSL2 中 Redis 已启动');
        console.log('运行: wsl --user root systemctl start redis-server');
        console.log('或参考: WSL2中安装Redis.md 文件');
        process.exit(1);
    }

    // 显示 Redis 信息
    const info = await manager.getInfo();
    if (info) {
        console.log('\n📊 Redis 服务器信息:');
        console.log(`   版本: ${info.Server?.redis_version}`);
        console.log(`   内存: ${info.Memory?.used_memory_human}`);
        console.log(`   连接数: ${info.Clients?.connected_clients}`);
    }

    // 简单测试
    console.log('\n🧪 运行功能测试...');

    // 测试缓存 K 线
    await manager.cacheKline('BTCUSDT', '1h', Date.now(), {
        open: '70000',
        high: '71000',
        low: '69500',
        close: '70500',
        volume: '1000'
    });
    console.log('  ✅ K 线缓存测试');

    // 测试信号缓存
    await manager.cacheSignal('DualMA', 'BTCUSDT', {
        signal: 'BUY',
        price: '70500',
        timestamp: Date.now()
    });
    console.log('  ✅ 信号缓存测试');

    // 测试错误计数
    const errorCount = await manager.incrementErrorCount('api');
    console.log(`  ✅ 错误计数: ${errorCount}`);

    console.log('\n✅ 所有测试通过！');

    // 清理
    await manager.disconnect();

    console.log('\n💡 下一步:');
    console.log('  1. 在 .env 文件中配置 Redis 密码');
    console.log('  2. 集成到交易系统中');
    console.log('  3. 参考: Redis在量化交易系统中的应用.md 文件');
}

// 导出管理器
module.exports = { RedisManager };

// 如果直接运行则执行测试
if (require.main === module) {
    main().catch(console.error);
}
