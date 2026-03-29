# 现货杠杆交易模块修复总结

## 修复日期
2026-03-29

## 问题汇总

### 1. 400 Client Error - 借币接口
```
Request failed: 400 Client Error: for url: https://api.binance.com/sapi/v1/margin/loan
Failed to borrow BTC: 400 Client Error: for url: https://api.binance.com/sapi/v1/margin/loan
```

**原因分析：**
- 借币数量精度不正确
- 未查询最大可借数量
- 参数格式可能不兼容

**修复措施：**
1. 添加 `_get_max_borrowable()` 方法查询最大可借
2. 添加 `_format_quantity_by_asset()` 按资产类型格式化数量
3. 确保使用 `isIsolated='FALSE'` 参数（全仓杠杆）
4. 借币前检查账户余额和可借额度

### 2. 400 Client Error - 下单接口
```
Failed to execute spot margin order: 400 Client Error: for url: https://api.binance.com/sapi/v1/margin/order
```

**原因分析：**
- 订单数量不符合 LOT_SIZE 过滤器要求
- 下单金额低于 MIN_NOTIONAL 要求
- 未根据交易对精度格式化数量

**修复措施：**
1. 添加 `_load_exchange_info()` 加载交易所信息
2. 添加 `_get_symbol_info()` 获取交易对精度
3. 添加 `_format_quantity_for_symbol()` 根据 step_size 格式化数量
4. 添加 `_format_price_for_symbol()` 格式化价格
5. 下单前检查最小下单金额

### 3. SSL 连接错误
```
SSL error: HTTPSConnectionPool(host='api.binance.com', port=443): Max retries exceeded
SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol
```

**原因分析：**
- 网络不稳定
- 代理/VPN连接中断
- 没有重试机制

**修复措施：**
1. 添加 `_make_request()` 重试机制（指数退避：1s, 2s, 4s）
2. 添加熔断器机制：连续10次错误后暂停交易5分钟
3. 处理多种错误类型：ProxyError, SSLError, ConnectionError, Timeout
4. 改进错误日志输出，包含错误码和详细信息

## 代码变更

### trading/spot_margin_executor.py

#### 新增功能：

1. **SymbolInfo 数据类**
```python
@dataclass
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: float
    max_qty: float
    step_size: float
    min_notional: float
    price_precision: int
    quantity_precision: int
```

2. **熔断器机制**
```python
_check_circuit_breaker()   # 检查熔断器状态
_record_error()            # 记录错误
_record_success()          # 记录成功
```

3. **精度处理**
```python
_load_exchange_info()              # 加载交易所信息
_get_precision_from_step_size()    # 计算精度
_format_quantity_for_symbol()      # 格式化数量
_format_price_for_symbol()         # 格式化价格
_format_quantity_by_asset()        # 按资产格式化
```

4. **借币改进**
```python
_get_max_borrowable()      # 查询最大可借
_borrow_asset()            # 改进借币逻辑
```

5. **API重试**
```python
_make_request()            # 带重试的HTTP请求
```

### live_trading_pro_v2_live_only.py

#### 新增配置：
```python
self.leverage_executor = SpotMarginExecutor(
    ...
    max_retries=3,           # API重试次数
    retry_delay=1.0          # 重试间隔
)
```

#### 新增熔断器检查：
```python
# Check circuit breaker status
if hasattr(self.leverage_executor, 'get_circuit_breaker_status'):
    cb_status = self.leverage_executor.get_circuit_breaker_status()
    if cb_status['is_open']:
        self.log.warning("Circuit breaker is OPEN...")
        time.sleep(60)
        continue
```

## 新增文件

1. **test_margin_executor_fix.py** - 修复验证脚本
2. **diagnose_margin_trading.py** - 诊断工具

## 使用说明

### 1. 运行诊断工具
```bash
python diagnose_margin_trading.py
```
检查API配置、权限和网络连接。

### 2. 运行修复验证
```bash
python test_margin_executor_fix.py
```
验证精度格式化、熔断器等逻辑。

### 3. 启动实盘交易
```bash
python run_live_margin.py
```

## 注意事项

1. **杠杆账户要求**：
   - 必须在币安开启杠杆账户
   - 需要转移资金到杠杆账户
   - API Key需要启用杠杆交易权限

2. **最小下单限制**：
   - BTCUSDT: 最小数量 0.00001 BTC
   - BTCUSDT: 最小金额 10 USDT

3. **熔断器机制**：
   - 连续10次API错误后自动熔断
   - 熔断后5分钟自动恢复
   - 熔断期间暂停下单

4. **日志查看**：
   - 详细错误信息记录在 `logs/pro_v2_YYYYMMDD.log`
   - 包含API错误码和详细消息

## 常见错误码

| 错误码 | 含义 | 解决方案 |
|--------|------|----------|
| -1100 | 参数包含非法字符 | 检查数量格式 |
| -1106 | 不需要的参数 | 修正API参数 |
| -2010 | 新订单被拒绝 | 检查余额和权限 |
| -3005 | 超过最大可借额度 | 减少借币数量 |
| -3006 | 借币失败 | 检查杠杆账户状态 |
| -3008 | 账户禁止借币 | 联系客服或检查风控 |
| -3010 | 账户禁止还款 | 联系客服 |
| -3015 | 借币功能已关闭 | 等待开放或换其他资产 |

## 后续优化建议

1. **监控告警**：添加Webhook/邮件通知，当熔断器触发或API失败率过高时告警
2. **自动恢复**：熔断器恢复后，先进行小额测试订单验证API正常
3. **多交易所支持**：将执行器抽象，支持多个交易所的杠杆交易
4. **订单查询**：添加订单状态查询和重同步机制，防止状态不一致
