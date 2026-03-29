#!/usr/bin/env node
/**
 * 测试 Redis 连接
 */

const redis = require('redis');

console.log('==========================================');
console.log('Redis 连接测试');
console.log('==========================================');

// 连接配置 - using WSL2 IP address
const config = {
    socket: {
        host: '192.168.18.62',
        port: 6379,
        connectTimeout: 5000,
        reconnectStrategy: (retries) => Math.min(retries * 50, 500)
    }
};

// 测试连接
async function testRedisConnection() {
    try {
        console.log('1/3: 尝试连接到 Redis...');
        const client = redis.createClient(config);

        client.on('error', (err) => {
            console.error('❌ Redis 连接错误:', err);
        });

        client.on('connect', () => {
            console.log('✅ Redis 连接成功');
        });

        client.on('ready', () => {
            console.log('✅ Redis 服务器就绪');
        });

        await client.connect();

        console.log('2/3: 测试基本操作...');

        // 测试 ping
        const pingResult = await client.ping();
        console.log(`  Ping: ${pingResult}`);

        // 测试设置和获取
        const testKey = `test:${Date.now()}`;
        const testValue = 'Hello Redis from Binance Trading System';

        await client.setEx(testKey, 300, testValue);
        console.log(`  设置键: ${testKey}`);

        const getResult = await client.get(testKey);
        console.log(`  获取值: ${getResult}`);

        // 测试删除
        const delResult = await client.del(testKey);
        console.log(`  删除键: ${testKey}`);

        console.log('3/3: 测试服务器信息...');

        // 获取服务器信息
        const info = await client.info('server');
        const serverInfo = parseRedisInfo(info);

        console.log(`  服务器版本: ${serverInfo.redis_version}`);
        console.log(`  运行模式: ${serverInfo.redis_mode}`);
        console.log(`  内存使用: ${serverInfo.used_memory_human}`);
        console.log(`  连接数: ${serverInfo.connected_clients}`);
        console.log(`  总键数: ${serverInfo.db0.keys}`);

        console.log('\n✅ 所有测试通过！');
        console.log('Redis 已成功配置并可正常使用。');

        await client.quit();
        return true;

    } catch (error) {
        console.error('❌ 测试失败:', error);

        console.log('\n⚠️  可能的解决方法:');
        console.log('1. 检查 WSL2 中 Redis 是否运行:');
        console.log('   wsl --user root systemctl status redis-server');
        console.log('2. 检查防火墙设置:');
        console.log('   New-NetFirewallRule -DisplayName "WSL2 Redis" -Direction Inbound -LocalPort 6379 -Protocol TCP -Action Allow');
        console.log('3. 检查 Redis 密码配置:');
        console.log('   wsl --user root cat /etc/redis/redis.conf | grep requirepass');

        return false;
    }
}

// 解析 Redis info 输出
function parseRedisInfo(info) {
    const lines = info.split('\r\n');
    const result = {};

    lines.forEach(line => {
        if (line && !line.startsWith('#')) {
            const [key, value] = line.split(':');
            if (key && value) {
                result[key] = value.trim();
            }
        }
    });

    // 解析数据库信息
    result.db0 = { keys: 0, expires: 0 };
    const dbMatch = info.match(/db0:keys=(\d+),expires=(\d+)/);
    if (dbMatch) {
        result.db0.keys = parseInt(dbMatch[1]);
        result.db0.expires = parseInt(dbMatch[2]);
    }

    return result;
}

// 主函数
async function main() {
    console.log('开始测试 Redis 连接...');
    const success = await testRedisConnection();

    if (!success) {
        console.log('💡 提示: 如果您还没有配置 Redis，请参考 WSL2中安装Redis.md 文件');
        console.log('或运行快速配置:');
        console.log('wsl --user root nano /etc/redis/redis.conf');
    }
}

main().catch(console.error);
