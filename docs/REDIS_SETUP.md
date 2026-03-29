# Redis 配置指南

## 架构

本项目使用 WSL2 中的 Redis 服务器，作为实时数据缓存层。

```
Windows (Node.js / Python) → WSL2 Redis (192.168.18.62:6379)
```

## 安装（WSL2）

```bash
# 进入 WSL2
wsl

# 安装 Redis
sudo apt-get update
sudo apt-get install -y redis-server

# 允许所有连接（默认只监听 127.0.0.1）
sudo sed -i 's/bind 127.0.0.1/bind 0.0.0.0/' /etc/redis/redis.conf
sudo sed -i 's/protected-mode yes/protected-mode no/' /etc/redis/redis.conf

# 启动并设置开机自启
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 验证
redis-cli ping  # 期望输出：PONG
```

## 获取 WSL2 IP

```bash
wsl -- ip addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}'
```

> WSL2 每次重启后 IP 可能变化，更新 `.env` 中的 `REDIS_HOST`。

## .env 配置

```env
REDIS_HOST=192.168.18.62   # WSL2 IP（或 localhost 如用端口转发）
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

## 使用示例

### Python

```python
from utils.redis_manager import RedisManager

redis = RedisManager()
redis.connect()
redis.cache_stats("test:key", "test value")
value = redis.get_stats("test:key")
redis.disconnect()
```

### Node.js

```javascript
const { RedisManager } = require('./redis_manager');

const redis = new RedisManager();
await redis.connect();
await redis.client.set('test:key', 'test value');
const value = await redis.client.get('test:key');
await redis.disconnect();
```

## 连接测试

```bash
# Python
python test_redis_simple.py

# Node.js
node test_redis_connection.js

# WSL2 bash 脚本
wsl --user root bash -c "cd /mnt/d/binance && ./test_redis_wsl.sh"
```

## 从 Windows 直连（需管理员权限）

```powershell
# 添加防火墙规则
New-NetFirewallRule -DisplayName "WSL2 Redis" -Direction Inbound -LocalPort 6379 -Protocol TCP -Action Allow

# 端口转发（WSL2 重启后需重新执行）
$wslIp = (wsl -- ip addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}').Trim()
netsh interface portproxy add v4tov4 listenport=6379 listenaddress=0.0.0.0 connectport=6379 connectaddress=$wslIp
```

## 常见问题

| 问题 | 解决方法 |
|------|----------|
| `Connection refused` | `wsl --user root systemctl start redis-server` |
| WSL2 IP 变化 | `wsl -- ip addr show eth0 ...` 获取新 IP，更新 `.env` |
| Windows 无法连接 | 配置防火墙和端口转发（见上方） |
