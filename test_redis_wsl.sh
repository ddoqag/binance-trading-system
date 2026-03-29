#!/usr/bin/env bash
# WSL2 Redis 测试脚本 (在 WSL2 内部运行)

echo "=========================================="
echo "Redis 连接测试 (WSL2)"
echo "=========================================="

# 进入项目目录
cd /mnt/d/binance

echo "1/3: 检查 Redis 服务状态..."
REDIS_STATUS=$(systemctl status redis-server 2>&1)
if echo "$REDIS_STATUS" | grep -q "active (running)"; then
    echo "✅ Redis 服务正在运行"
else
    echo "❌ Redis 服务未运行"
    echo "启动 Redis: sudo systemctl start redis-server"
    exit 1
fi

echo "2/3: 测试 Node.js 连接..."
if node test_redis_connection.js; then
    echo "✅ Node.js 连接测试成功"
else
    echo "❌ Node.js 连接测试失败"
fi

echo "3/3: 测试 Python 连接..."
# 检查 Python 是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 未安装"
    exit 1
fi

# 检查 redis 包是否已安装
if python3 -c "import redis" 2>/dev/null; then
    if python3 test_redis_simple.py; then
        echo "✅ Python 连接测试成功"
    else
        echo "❌ Python 连接测试失败"
    fi
else
    echo "⚠️  Python redis 包未安装"
    echo "正在安装依赖..."
    pip3 install -r requirements.txt 2>/dev/null || pip install -r requirements.txt
    if python3 test_redis_simple.py; then
        echo "✅ Python 连接测试成功"
    else
        echo "❌ Python 连接测试失败"
    fi
fi

echo "------------------------------------------"
echo "Redis 信息: $(redis-cli info server | grep redis_version)"
echo "WSL2 IP地址: $(ip addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)"
echo "端口: 6379"
echo "------------------------------------------"
echo "✅ 所有测试完成!"

