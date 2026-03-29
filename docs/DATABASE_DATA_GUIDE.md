# 使用数据库数据训练 - 完整指南

## 概述

本指南说明如何：
1. 从币安 API 获取更多数据
2. 存入 PostgreSQL 数据库
3. 从数据库加载数据并训练 RL/因子模型

---

## 第一步：准备数据库

### 1.1 确保 PostgreSQL 已启动

```bash
# Windows
# 检查 PostgreSQL 服务是否运行

# 或使用 pgAdmin 查看
```

### 1.2 创建数据库（如果还没有）

```sql
-- 在 psql 中执行
CREATE DATABASE binance;
```

或命令行：
```bash
createdb -U postgres binance
```

### 1.3 配置数据库密码

编辑 `.env` 文件：
```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=binance
DB_USER=postgres
DB_PASSWORD=your_password_here
```

---

## 第二步：从币安 API 获取数据并存入数据库

### 2.1 运行数据获取脚本

```bash
cd D:/binance
node fetch-and-save-to-db.js
```

**这个脚本会：**
- 获取 5 个交易对：BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
- 获取 6 个时间周期：1m, 5m, 15m, 1h, 4h, 1d
- 每个获取 1000 根 K 线
- 同时保存 CSV 和数据库
- 自动去重（已存在的数据会更新）

### 2.2 自定义配置（可选）

编辑 `fetch-and-save-to-db.js` 中的 `CONFIG`：

```javascript
const CONFIG = {
  symbols: ['BTCUSDT', 'ETHUSDT'],  // 只获取这两个
  intervals: ['1h', '4h'],           // 只获取这两个周期
  limit: 1000,
  saveToCSV: true,
  saveToDB: true
};
```

---

## 第三步：从数据库加载数据

### 3.1 在 Notebook 中使用数据库数据

#### 因子研究：使用数据库数据

编辑 `notebooks/utils.py` 中的 `load_binance_data`，或直接使用：

```python
from data.loader import load_klines_from_db

# 从数据库加载 BTCUSDT 1小时数据
df = load_klines_from_db(
    symbol='BTCUSDT',
    interval='1h',
    db_config={
        'host': 'localhost',
        'port': 5432,
        'database': 'binance',
        'user': 'postgres',
        'password': '362232'
    }
)

print(f"Loaded {len(df)} rows from database")
```

#### RL 研究：使用数据库数据

同样在 `notebooks/rl_utils.py` 中：

```python
from data.loader import load_klines_from_db

df = load_klines_from_db('BTCUSDT', '1h')
```

### 3.2 更新演示脚本使用数据库（可选）

修改 `demo_factor_research.py`：

```python
# 替换原来的加载部分
from notebooks.utils import load_binance_data
from data.loader import load_klines_from_db

# 先尝试数据库
df = load_klines_from_db('BTCUSDT', '1h')

# 如果数据库没有，尝试 CSV
if df.empty:
    df = load_binance_data('BTCUSDT', '1h')

# 如果都没有，用模拟数据
if df.empty:
    df = generate_sample_data(...)
```

---

## 第四步：验证数据

### 4.1 检查数据库中的数据量

```sql
-- 连接到 binance 数据库
\c binance

-- 查看每个交易对和时间周期的数据量
SELECT symbol, interval, COUNT(*)
FROM klines
GROUP BY symbol, interval
ORDER BY symbol, interval;
```

或使用 Python：

```python
import psycopg2

conn = psycopg2.connect(
    host='localhost',
    port=5432,
    database='binance',
    user='postgres',
    password='362232'
)

query = """
    SELECT symbol, interval, COUNT(*) as count
    FROM klines
    GROUP BY symbol, interval
    ORDER BY symbol, interval
"""

df = pd.read_sql(query, conn)
print(df)
conn.close()
```

---

## 完整工作流程示例

```bash
# 1. 获取数据并存入数据库
node fetch-and-save-to-db.js

# 2. 验证数据已存入
# (查看输出或用 SQL 查询)

# 3. 运行因子研究（使用数据库数据）
cd notebooks
# (先修改 demo_factor_research.py 使用数据库)
python demo_factor_research.py

# 4. 运行 RL 研究（使用数据库数据）
python demo_rl_research.py
```

---

## 常见问题

### Q: 没有 PostgreSQL 怎么办？

A: 可以只用 CSV 数据，脚本也会保存 CSV 到 `data/` 目录。

### Q: 数据库连接失败？

A: 检查：
1. PostgreSQL 服务是否启动
2. 用户名/密码是否正确
3. 数据库 "binance" 是否已创建

### Q: 想获取更多历史数据？

A: 币安 API 每次最多 1000 根。要获取更多，需要多次调用并指定 `startTime`/`endTime`。

### Q: 数据量还是不够？

A: 可以：
1. 多次运行脚本获取不同时间段
2. 使用已下载的 CSV 文件（项目已有一些）
3. 结合使用模拟数据

---

## 快速开始（不配置数据库）

如果不想配置数据库，直接用已有的 CSV 数据：

```bash
# 直接运行演示，会自动加载 data/ 目录的 CSV
cd notebooks
python demo_factor_research.py
python demo_rl_research.py
```

已有的 CSV 数据：
- BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
- 1m, 5m, 15m, 1h, 4h, 1d
- 2026-03-09 ~ 2026-03-10
