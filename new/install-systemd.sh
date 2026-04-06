#!/bin/bash
# Binance Trader systemd 服务安装脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="binance-trader"
SERVICE_FILE="$SCRIPT_DIR/binance-trader.service"

echo "======================================"
echo "  Binance Trader Systemd Setup"
echo "======================================"

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

# 创建 trader 用户（如果不存在）
if ! id -u trader &>/dev/null; then
    echo "[1/6] 创建 trader 用户..."
    useradd -r -s /bin/false -m -d /opt/binance-trader trader
else
    echo "[1/6] trader 用户已存在"
fi

# 设置目录权限
echo "[2/6] 设置目录权限..."
mkdir -p /opt/binance-trader
cp -r "$SCRIPT_DIR"/* /opt/binance-trader/
chown -R trader:trader /opt/binance-trader
chmod 750 /opt/binance-trader

# 设置环境变量文件权限
if [ -f /opt/binance-trader/.env ]; then
    chmod 640 /opt/binance-trader/.env
fi

# 安装 Python 依赖
echo "[3/6] 安装 Python 依赖..."
if [ -f /opt/binance-trader/requirements.txt ]; then
    pip3 install -r /opt/binance-trader/requirements.txt
fi

# 安装 systemd 服务
echo "[4/6] 安装 systemd 服务..."
cp "$SERVICE_FILE" /etc/systemd/system/
systemctl daemon-reload

# 启用服务（但不启动）
echo "[5/6] 启用服务..."
systemctl enable $SERVICE_NAME

echo "[6/6] 完成！"
echo ""
echo "======================================"
echo "  安装完成"
echo "======================================"
echo ""
echo "请确保已配置 /opt/binance-trader/.env 文件："
echo "  - BINANCE_API_KEY"
echo "  - BINANCE_API_SECRET"
echo "  - TELEGRAM_BOT_TOKEN (可选)"
echo "  - TELEGRAM_CHAT_ID (可选)"
echo ""
echo "管理命令："
echo "  启动:   sudo systemctl start $SERVICE_NAME"
echo "  停止:   sudo systemctl stop $SERVICE_NAME"
echo "  重启:   sudo systemctl restart $SERVICE_NAME"
echo "  状态:   sudo systemctl status $SERVICE_NAME"
echo "  日志:   sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "查看实时日志："
echo "  sudo journalctl -u $SERVICE_NAME -f"
