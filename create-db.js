// @ts-check
const { Pool } = require('pg');

// 先连接到 postgres 数据库来创建 binance 数据库
const postgresPool = new Pool({
  host: 'localhost',
  port: 5432,
  database: 'postgres',
  user: 'postgres',
  password: '362232'
});

async function createDatabase() {
  console.log('正在连接到 PostgreSQL...');

  const client = await postgresPool.connect();

  try {
    // 检查数据库是否已存在
    const checkResult = await client.query(
      "SELECT 1 FROM pg_database WHERE datname = 'binance'"
    );

    if (checkResult.rows.length > 0) {
      console.log('✓ 数据库 binance 已存在');
    } else {
      console.log('正在创建数据库 binance...');
      await client.query('CREATE DATABASE binance');
      console.log('✓ 数据库 binance 创建成功');
    }

  } finally {
    client.release();
    await postgresPool.end();
  }
}

createDatabase().catch(err => {
  console.error('✗ 创建数据库失败:', err.message);
  process.exit(1);
});
