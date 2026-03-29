// @ts-check
const { Client } = require('pg');

/**
 * PostgreSQL 配置
 */
const baseConfig = {
  host: 'localhost',
  port: 5432,
  user: 'postgres',
  password: '362232'
};

/**
 * 创建 binance 数据库
 */
async function createDatabase() {
  console.log('正在连接到 PostgreSQL...');

  const client = new Client({
    ...baseConfig,
    database: 'postgres' // 连接到默认数据库
  });

  try {
    await client.connect();
    console.log('✓ 已连接到 PostgreSQL');

    // 检查数据库是否已存在
    const result = await client.query(
      "SELECT 1 FROM pg_database WHERE datname = 'binance'"
    );

    if (result.rows.length > 0) {
      console.log('✓ 数据库 binance 已存在');
    } else {
      console.log('正在创建数据库 binance...');
      await client.query('CREATE DATABASE binance');
      console.log('✓ 数据库 binance 创建成功');
    }

  } finally {
    await client.end();
  }
}

/**
 * 主函数
 */
async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  设置币安数据库');
  console.log('═══════════════════════════════════════════════\n');

  try {
    await createDatabase();
    console.log('\n✓ 数据库准备完成！');
    console.log('\n下一步: 运行 npm run init-db 来创建表结构');
  } catch (error) {
    console.error('\n✗ 出错:', error.message);
    if (error.code === 'ECONNREFUSED') {
      console.error('\n请检查:');
      console.error('  1. PostgreSQL 服务是否已启动');
      console.error('  2. 端口 5432 是否正确');
    } else if (error.code === '28P01') {
      console.error('\n请检查:');
      console.error('  1. 用户名 postgres 是否正确');
      console.error('  2. 密码 362232 是否正确');
    }
    process.exit(1);
  }
}

main();
