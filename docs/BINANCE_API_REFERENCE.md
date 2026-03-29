# 币安现货 API 接口参考 - Binance Spot API Reference

> 整理自：https://developers.binance.com/docs/zh-CN/binance-spot-api-docs

## 目录

- [市场数据接口](#市场数据接口)
- [交易/订单接口](#交易订单接口)
- [订单列表接口](#订单列表接口)
- [账户/资产接口](#账户资产接口)
- [价格与执行规则](#价格与执行规则)
- [用户数据流](#用户数据流)
- [速率限制](#速率限制)
- [已废弃接口](#已废弃接口)

---

## 市场数据接口

| 方法 | 接口 | 说明 |
|------|------|------|
| GET | `/api/v3/depth` | 获取订单簿深度 |
| GET | `/api/v3/ticker/price` | 获取最新价格 |
| GET | `/api/v3/ticker/bookTicker` | 获取最优挂单价格/数量 |
| GET | `/api/v3/ticker/24hr` | 获取 24 小时价格变动统计 |
| GET | `/api/v3/ticker/tradingDay` | 获取交易日行情 |
| GET | `/api/v3/ticker` | 获取带窗口大小的价格行情 |
| GET | `/api/v3/aggTrades` | 获取聚合交易记录 |
| GET | `/api/v3/klines` | 获取 K 线/蜡烛图数据 |
| GET | `/api/v3/uiKlines` | 获取 UI 用 K 线数据 |
| GET | `/api/v3/trades` | 获取最近成交记录 |
| GET | `/api/v3/historicalTrades` | 获取历史成交记录 |
| GET | `/api/v3/avgPrice` | 获取平均价格 |
| GET | `/api/v3/exchangeInfo` | 获取交易规则和交易对信息 |

---

## 交易/订单接口

| 方法 | 接口 | 说明 |
|------|------|------|
| POST | `/api/v3/order` | 下单 |
| POST | `/api/v3/sor/order` | 智能订单路由 (SOR) 下单 |
| POST | `/api/v3/order/test` | 测试下单（不执行） |
| POST | `/api/v3/sor/order/test` | 测试 SOR 下单（不执行） |
| POST | `/api/v3/order/oco` | 下 OCO（二选一）订单 |
| POST | `/api/v3/orderList/oco` | 下 OCO 订单列表 |
| POST | `/api/v3/orderList/oto` | 下 OTO（触发型）订单列表 |
| POST | `/api/v3/orderList/otoco` | 下 OTOCO 订单列表 |
| POST | `/api/v3/orderList/opo` | 下 OPO 订单列表 |
| POST | `/api/v3/orderList/opoco` | 下 OPOCO 订单列表 |
| POST | `/api/v3/order/cancelReplace` | 撤销并替换订单 |
| GET | `/api/v3/order` | 查询订单状态 |
| GET | `/api/v3/openOrders` | 查询所有当前挂单 |
| GET | `/api/v3/allOrders` | 查询所有订单 |
| DELETE | `/api/v3/order` | 撤销订单 |
| DELETE | `/api/v3/openOrders` | 撤销所有挂单 |
| PUT | `/api/v3/order/amend/keepPriority` | 修改订单（保持优先级） |

---

## 订单列表接口

| 方法 | 接口 | 说明 |
|------|------|------|
| GET | `/api/v3/openOrderList` | 查询开放订单列表 |
| GET | `/api/v3/allOrderList` | 查询所有订单列表 |
| GET | `/api/v3/orderList` | 查询订单列表状态 |
| DELETE | `/api/v3/orderList` | 撤销订单列表 |

---

## 账户/资产接口

| 方法 | 接口 | 说明 |
|------|------|------|
| GET | `/api/v3/account` | 获取账户信息 |
| GET | `/api/v3/account/commission` | 获取手续费率 |
| GET | `/api/v3/myTrades` | 获取账户成交记录 |
| GET | `/api/v3/myPreventedMatches` | 获取 STP 阻止的成交 |
| GET | `/api/v3/myAllocations` | 获取分配历史 |
| GET | `/api/v3/myFilters` | 获取账户过滤器 |

---

## 价格与执行规则

| 方法 | 接口 | 说明 |
|------|------|------|
| GET | `/api/v3/referencePrice` | 获取参考价格 |
| GET | `/api/v3/referencePrice/calculation` | 获取参考价格计算 |
| GET | `/api/v3/executionRules` | 获取执行规则 |

---

## 用户数据流

| 方法 | 接口 | 说明 |
|------|------|------|
| POST | `/api/v3/userDataStream` | 启动用户数据流（已废弃） |
| PUT | `/api/v3/userDataStream` | 保持用户数据流活跃（已废弃） |
| DELETE | `/api/v3/userDataStream` | 关闭用户数据流（已废弃） |

---

## 速率限制

| 方法 | 接口 | 说明 |
|------|------|------|
| GET | `/api/v3/rateLimit/order` | 获取当前订单数速率限制 |

---

## 已废弃接口

| 方法 | 接口 | 说明 | 废弃日期 |
|------|------|------|----------|
| GET | `/api/v1/ping` | Ping | 2026-03-25 |
| GET | `/api/v1/time` | 服务器时间 | 2026-03-25 |
| POST | `/api/v1/userDataStream` | 旧版用户数据流 | - |
| GET | `/api/v1/ticker/bookTicker` | - | - |
| GET | `/api/v1/ticker/price` | - | - |
| GET | `/api/v1/klines` | - | - |
| GET | `/api/v1/historicalTrades` | - | - |
| GET | `/api/v1/depth` | - | - |
| GET | `/api/v1/aggTrades` | - | - |
| GET | `/api/v1/ticker/24hr` | - | - |

---

## 快速参考

### 最常用接口

| 用途 | 接口 |
|------|------|
| 获取 K 线 | `GET /api/v3/klines` |
| 获取订单簿 | `GET /api/v3/depth` |
| 获取 24h 行情 | `GET /api/v3/ticker/24hr` |
| 获取账户信息 | `GET /api/v3/account` |
| 下单 | `POST /api/v3/order` |
| 查询订单 | `GET /api/v3/order` |
| 撤销订单 | `DELETE /api/v3/order` |
| 查询成交 | `GET /api/v3/myTrades` |
| 获取交易规则 | `GET /api/v3/exchangeInfo` |

---

## 相关链接

- 官方文档：https://developers.binance.com/docs/zh-CN/binance-spot-api-docs
- GitHub SDK：https://github.com/binance/binance-connector-node
- 本项目 SDK 文档：../SDK-README.md
