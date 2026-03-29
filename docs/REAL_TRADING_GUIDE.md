# 实盘交易使用指南 - Real Trading Guide

> ⚠️ **警告：实盘交易有风险，请仔细阅读本文档并充分测试后再使用！**

---

## 目录
- [风险提示](#风险提示)
- [前置准备](#前置准备)
- [配置步骤](#配置步骤)
- [测试网演练](#测试网演练)
- [实盘交易](#实盘交易)
- [安全措施](#安全措施)
- [常见问题](#常见问题)

---

## 风险提示

### 重要警告

1. **资金风险**
   - 实盘交易会损失真实资金
   - 只投入你能承受损失的资金
   - 建议先用小资金测试

2. **策略风险**
   - 历史回测不代表未来表现
   - 市场行情变化可能导致策略失效
   - 需持续监控策略表现

3. **技术风险**
   - API 故障可能导致无法下单/撤单
   - 网络问题可能导致订单重复发送
   - 程序 bug 可能导致意外交易

---

## 前置准备

### 1. 币安账户准备

1. **注册币安账户**
   - 访问 https://www.binance.com
   - 完成 KYC 认证

2. **创建 API Key**
   - 登录币安 → 账户 → API 管理
   - 点击「创建 API」
   - 设置标签（如：`quant-trading-bot`）
   - 完成安全验证

3. **配置 API 权限**
   - ✅ 启用现货交易
   - ❌ 不启用杠杆交易（除非需要）
   - ❌ 不允许提现（强烈推荐）
   - ✅ 启用读取信息

4. **配置 IP 限制**（强烈推荐）
   - 在 API 管理页面找到「IP 访问限制」
   - 选择「限制访问的 IP」
   - 输入你的服务器/本地 IP 地址
   - 点击「确认保存」

### 2. 软件依赖安装

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 确认 python-binance 已安装
pip show python-binance
```

---

## 配置步骤

### 1. 环境变量配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API 凭证：

```bash
# ============================================
# 币安 API 配置
# ============================================
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# ============================================
# 交易配置
# ============================================
PAPER_TRADING=false  # 设置为 false 启用实盘
INITIAL_CAPITAL=1000  # 实盘请用小资金开始
MAX_POSITION_SIZE=0.1  # 总仓位 10%（保守）
MAX_SINGLE_POSITION=0.05  # 单笔 5%（保守）
```

### 2. 配置验证

创建验证脚本 `verify_config.py`：

```python
#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from trading import BinanceClient

# 加载配置
load_dotenv()

print("="*60)
print("配置验证")
print("="*60)

# 检查环境变量
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

if not api_key or api_key == 'your_api_key_here':
    print("❌ BINANCE_API_KEY 未配置")
else:
    print(f"✅ BINANCE_API_KEY: {api_key[:10]}...")

if not api_secret or api_secret == 'your_api_secret_here':
    print("❌ BINANCE_API_SECRET 未配置")
else:
    print(f"✅ BINANCE_API_SECRET: {api_secret[:10]}...")

paper_trading = os.getenv('PAPER_TRADING', 'true').lower() in ('true', '1', 'yes')
print(f"📋 模拟交易模式: {'是' if paper_trading else '否'}")

print("\n" + "="*60)
print("测试网连接测试")
print("="*60)

# 测试测试网连接
try:
    client = BinanceClient(api_key, api_secret, testnet=True)
    if client.connect():
        print("✅ 测试网连接成功")

        # 获取测试网价格
        price = client.get_current_price('BTCUSDT')
        print(f"📈 BTCUSDT 价格: {price}")

        # 获取余额（测试网）
        balance = client.get_balance('USDT')
        if balance:
            print(f"💰 USDT 余额: {balance.free} (free), {balance.locked} (locked)")
    else:
        print("❌ 测试网连接失败")
except Exception as e:
    print(f"❌ 测试网连接异常: {e}")

print("\n" + "="*60)
print("配置验证完成")
print("="*60)
```

运行验证：

```bash
python verify_config.py
```

---

## 测试网演练

### 1. 测试网测试脚本

创建 `testnet_demo.py`：

```python
#!/usr/bin/env python3
"""
币安测试网交易演示
"""

import os
import time
from dotenv import load_dotenv
from trading import BinanceClient, TradingExecutor, OrderSide, OrderType

# 加载配置
load_dotenv()

def main():
    print("="*60)
    print("币安测试网交易演示")
    print("="*60)

    # 初始化币安客户端（测试网）
    client = BinanceClient(
        api_key=os.getenv('BINANCE_API_KEY'),
        api_secret=os.getenv('BINANCE_API_SECRET'),
        testnet=True
    )

    if not client.connect():
        print("❌ 连接失败")
        return

    print("✅ 连接成功\n")

    # 1. 获取市场信息
    print("1. 获取市场信息...")
    symbol = 'BTCUSDT'
    market_info = client.get_market_info(symbol)
    if market_info:
        print(f"   交易对: {market_info.symbol}")
        print(f"   价格精度: {market_info.price_precision}")
        print(f"   数量精度: {market_info.quantity_precision}")
        print(f"   最小数量: {market_info.min_quantity}")
        print(f"   最小名义: {market_info.min_notional}\n")

    # 2. 获取当前价格
    print("2. 获取当前价格...")
    price = client.get_current_price(symbol)
    print(f"   BTCUSDT 当前价格: {price}\n")

    # 3. 查询余额
    print("3. 查询余额...")
    balances = client.get_all_balances()
    for balance in balances:
        print(f"   {balance.asset}: {balance.free} (free), {balance.locked} (locked)")
    print()

    # 4. 初始化交易执行器（测试网 = 实盘模式，但连接的是测试网）
    print("4. 初始化交易执行器...")
    executor = TradingExecutor(
        is_paper_trading=False,  # 实盘模式（但连接测试网）
        binance_client=client,
        commission_rate=0.001
    )
    print("   交易执行器初始化完成\n")

    # 5. 测试下小额订单（测试网）
    print("5. 测试下单（测试网）...")
    print("   ⚠️  这是测试网，不会损失真实资金")

    # 获取价格，计算小额订单
    current_price = client.get_current_price(symbol)
    min_notional = market_info.min_notional if market_info else 10.0
    order_quantity = (min_notional * 2) / current_price  # 稍微大于最小名义
    order_quantity = round(order_quantity, market_info.quantity_precision if market_info else 6)

    print(f"   订单数量: {order_quantity}")
    print(f"   订单价值: {order_quantity * current_price:.2f} USDT")

    # 确认
    confirm = input("\n确认在测试网下单? (yes/no): ")
    if confirm.lower() != 'yes':
        print("   已取消")
        return

    # 下单
    order = executor.place_order(
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=order_quantity,
        current_price=current_price
    )

    if order:
        print(f"\n   ✅ 订单已提交")
        print(f"   订单 ID: {order.order_id}")
        print(f"   状态: {order.status}")
        print(f"   成交数量: {order.filled_quantity}")
        print(f"   成交均价: {order.avg_price}")

        # 等待一下
        print("\n   等待 2 秒后查询订单状态...")
        time.sleep(2)

        # 查询订单
        updated_order = executor.sync_order_status(order.order_id)
        if updated_order:
            print(f"\n   最新状态: {updated_order.status}")
            print(f"   成交数量: {updated_order.filled_quantity}")
    else:
        print("   ❌ 订单提交失败")

    print("\n" + "="*60)
    print("演示完成")
    print("="*60)

if __name__ == '__main__':
    main()
```

### 2. 运行测试网演练

```bash
python testnet_demo.py
```

**测试网获取测试币：**
- 访问 https://testnet.binance.vision/
- 点击「Create Test Account」获取测试币

---

## 实盘交易

### 1. 实盘前检查清单

- [ ] 已在测试网充分测试策略
- [ ] 已测试订单下单、查询、撤销功能
- [ ] 已配置 IP 白名单
- [ ] 已禁用 API 提现权限
- [ ] 已设置小仓位（单笔 < 5%，总仓位 < 20%）
- [ ] 已准备好紧急停止预案
- [ ] 只投入能承受损失的资金

### 2. 实盘交易代码示例

创建 `real_trading_example.py`：

```python
#!/usr/bin/env python3
"""
实盘交易示例 - 谨慎使用！
"""

import os
import time
import logging
from dotenv import load_dotenv

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from trading import (
    BinanceClient,
    TradingExecutor,
    OrderSide,
    OrderType
)
from config.settings import get_settings

# 加载配置
load_dotenv()
settings = get_settings()

def emergency_check(executor: TradingExecutor) -> bool:
    """紧急检查"""
    # 这里可以添加你的紧急条件
    # 例如：单笔亏损 > 2%，日亏损 > 5% 等
    return False

def main():
    print("="*60)
    print("⚠️  实盘交易 - 请谨慎使用！")
    print("="*60)

    # 确认
    confirm = input("\n确认要使用实盘交易? (type 'REAL-MONEY' to confirm): ")
    if confirm != 'REAL-MONEY':
        print("已取消")
        return

    # 再次确认
    confirm2 = input("\n最后确认：你了解实盘交易的风险吗? (yes/no): ")
    if confirm2.lower() != 'yes':
        print("已取消")
        return

    print("\n开始初始化...")

    # 初始化币安客户端（实盘）
    client = BinanceClient(
        api_key=os.getenv('BINANCE_API_KEY'),
        api_secret=os.getenv('BINANCE_API_SECRET'),
        testnet=False  # ⚠️ 实盘！
    )

    if not client.connect():
        print("❌ 连接失败")
        return

    print("✅ 连接成功\n")

    # 初始化交易执行器
    executor = TradingExecutor(
        is_paper_trading=False,  # ⚠️ 实盘模式！
        binance_client=client,
        commission_rate=settings.trading.commission_rate
    )

    # 查询余额
    print("当前余额：")
    balances = client.get_all_balances()
    for balance in balances:
        print(f"  {balance.asset}: {balance.free} (free)")

    # 获取价格
    symbol = settings.trading.symbol
    price = client.get_current_price(symbol)
    print(f"\n{symbol} 当前价格: {price}")

    try:
        # 主循环 - 这里只是示例，实际策略会更复杂
        print("\n开始交易循环（按 Ctrl+C 停止）...")

        while True:
            # 紧急检查
            if emergency_check(executor):
                print("⚠️  触发紧急条件！")
                executor.emergency_stop()
                break

            # 检查是否已紧急停止
            if client.is_emergency_stopped():
                print("⚠️  紧急停止已激活，退出")
                break

            # 你的策略逻辑在这里
            # ...

            # 同步订单状态
            executor.sync_all_open_orders()

            # 等待
            time.sleep(60)  # 每分钟检查一次

    except KeyboardInterrupt:
        print("\n\n收到停止信号")
        print("是否撤销所有未完成订单?")
        cancel = input("(yes/no): ")
        if cancel.lower() == 'yes':
            executor.binance_client.cancel_all_open_orders()
            print("已撤销所有订单")

    print("\n交易结束")

if __name__ == '__main__':
    main()
```

### 3. 运行实盘交易

```bash
# 先用小资金测试
python real_trading_example.py
```

---

## 安全措施

### 1. 多层安全检查

| 层级 | 措施 | 说明 |
|------|------|------|
| L1 | API 权限限制 | 不启用提现，启用 IP 白名单 |
| L2 | 资金限制 | 单笔仓位 < 5%，总仓位 < 20% |
| L3 | 止损止盈 | 每笔订单设止损，日亏损 > 5% 停止 |
| L4 | 程序监控 | 实时监控 PnL，异常时紧急停止 |
| L5 | 人工监控 | 定期检查账户和订单 |

### 2. 紧急停止

代码中内置了紧急停止功能：

```python
# 激活紧急停止
executor.emergency_stop()
# 或
client.emergency_stop()

# 检查状态
client.is_emergency_stopped()

# 重置
client.reset_emergency_stop()
```

紧急停止会：
- 撤销所有未完成订单
- 阻止新订单提交
- 记录紧急停止日志

### 3. 风险监控建议

```python
def check_risk_limits(daily_pnl: float, position_size: float,
                      max_daily_loss: float = -0.05,
                      max_position: float = 0.2) -> bool:
    """
    检查风险限制

    Returns:
        True = 触发风险限制，需要停止
    """
    if daily_pnl < max_daily_loss:
        return True  # 日亏损超限
    if position_size > max_position:
        return True  # 仓位超限
    return False
```

---

## 常见问题

### Q: 测试网和实盘有什么区别？

| 项目 | 测试网 | 实盘 |
|------|--------|------|
| 资金 | 测试币（无价值） | 真实资金 |
| API | testnet.binance.vision | api.binance.com |
| 订单簿 | 模拟 | 真实市场 |
| 滑点 | 可能不同 | 真实滑点 |
| 流动性 | 较低 | 高 |

### Q: 如何获取测试网币？

访问 https://testnet.binance.vision/，点击「Create Test Account」可以获取测试网 BTC 和 USDT。

### Q: 实盘交易最小资金是多少？

取决于交易对的最小名义值（MIN_NOTIONAL），通常 BTCUSDT 是 10 USDT。建议先用 100-500 USDT 测试。

### Q: 程序崩溃了怎么办？

1. 立即登录币安网页版/APP
2. 手动检查订单状态
3. 如有需要，手动撤销未完成订单
4. 分析程序崩溃原因
5. 修复后先用测试网验证

### Q: 如何监控实盘交易？

- 币安 APP 推送通知
- 程序日志监控
- 定期查看账户余额和订单
- 设置价格和 PnL 告警

---

## 相关文档

- [环境变量配置](./ENVIRONMENT_VARIABLES.md)
- [币安 API 参考](./BINANCE_API_REFERENCE.md)
- [配置使用指南](./CONFIGURATION_GUIDE.md)

---

**最后更新**: 2026-03-16
