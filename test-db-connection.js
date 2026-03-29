#!/usr/bin/env node

const { Pool } = require('pg');
const { dbConfig } = require('./config/config.js');

console.log('═══════════════════════════════════════════════');
console.log('  PostgreSQL 数据库连接测试');
console.log('═══════════════════════════════════════════════');
console.log('');

// 显示连接配置（隐藏密码）
console.log('连接配置:');
console.log(`  主机: ${dbConfig.host}:${dbConfig.port}`);
console.log(`  数据库: ${dbConfig.database}`);
console.log(`  用户: ${dbConfig.user}`);
console.log(`  密码: ***`);
console.log('');

// 创建连接池
const pool = new Pool(dbConfig);

// 测试连接函数
async function testConnection() {
  console.log('正在测试数据库连接...');

  try {
    // 尝试连接并执行简单查询
    const client = await pool.connect();
    console.log('✓ 连接成功');

    // 测试查询
    console.log('正在执行测试查询...');
    const result = await client.query('SELECT NOW() as current_time');

    console.log(`✓ 时间同步成功: ${result.rows[0].current_time}`);

    // 查询表结构
    console.log('正在检查数据库表...');
    const tablesResult = await client.query(`
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
      ORDER BY table_name
    `);

    console.log(`✓ 找到 ${tablesResult.rows.length} 个表: ${tablesResult.rows.map(r => r.table_name).join(', ')}`);

    // 检查 klines 表
    if (tablesResult.rows.some(row => row.table_name === 'klines')) {
      const klinesCount = await client.query('SELECT COUNT(*) as count FROM klines');
      console.log(`✓ klines 表数据量: ${klinesCount.rows[0].count}`);
    } else {
      console.log('⚠️  klines 表尚未创建，请运行 npm run init-db');
    }

    client.release();
    console.log('');
    console.log('✅ 数据库连接测试完成！');

  } catch (error) {
    console.error('');
    console.error('❌ 连接失败:');
    console.error(`   ${error.message}`);

    if (error.code === 'ECONNREFUSED') {
      console.error('');
      console.error('可能的原因:');
      console.error('  1. PostgreSQL 服务器未运行');
      console.error('  2. 防火墙阻止了连接');
      console.error('  3. 主机或端口配置错误');
    } else if (error.code === '3D000') {
      console.error('');
      console.error('可能的原因:');
      console.error('  1. 数据库不存在');
      console.error('  2. 数据库名称配置错误');
    } else if (error.code === '28P01') {
      console.error('');
      console.error('可能的原因:');
      console.error('  1. 用户名或密码错误');
    }

    console.error('');
    console.error('请检查:');
    console.error('  - 数据库是否正在运行');
    console.error('  - 连接配置是否正确');
    console.error('  - 数据库权限是否正常');
    process.exit(1);
  }
}

// 执行测试
testConnection().finally(() => {
  pool.end();
});
