// @ts-check
const { initDatabase, close } = require('./database');
const { dbConfig } = require('./config/config.js');

/**
 * 初始化币安数据库
 */
async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  初始化币安 PostgreSQL 数据库');
  console.log('═══════════════════════════════════════════════\n');

  console.log('数据库配置:');
  console.log(`  Host:     ${dbConfig.host}`);
  console.log(`  Port:     ${dbConfig.port}`);
  console.log(`  Database: ${dbConfig.database}`);
  console.log(`  User:     ${dbConfig.user}`);
  console.log('');

  try {
    await initDatabase();
    console.log('\n✓ 数据库初始化成功！');
    console.log('\n已创建的表:');
    console.log('  - symbols:           交易对元数据表');
    console.log('  - trade_calendar:    交易日历表');
    console.log('  - klines:            K线数据表');
    console.log('  - ticker_24hr:       24小时行情表');
    console.log('  - order_book:        订单簿表');
    console.log('  - indicator_configs: 技术指标配置表');
    console.log('  - indicator_values:  技术指标结果表');
  } catch (error) {
    console.error('\n✗ 数据库初始化失败:', error.message);
    console.error('\n请检查:');
    console.error('  1. PostgreSQL 是否启动');
    console.error(`  2. 数据库 "${dbConfig.database}" 是否已创建`);
    console.error('  3. 用户名/密码是否正确');
    process.exit(1);
  } finally {
    await close();
  }
}

// 创建数据库的 SQL 提示（使用实际配置值）
const createDBSQL = `
-- 在 psql 中执行以下命令创建数据库:
CREATE DATABASE ${dbConfig.database};
-- 或者在命令行执行:
-- createdb -U ${dbConfig.user} ${dbConfig.database}
`;

console.log(createDBSQL);

main();
