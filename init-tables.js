// @ts-check
const { initDatabase, close } = require('./database');

async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  初始化数据库表结构');
  console.log('═══════════════════════════════════════════════\n');

  try {
    await initDatabase();
    console.log('\n✓ 表结构初始化完成！');
  } catch (error) {
    console.error('\n✗ 初始化失败:', error.message);
    if (error.stack) {
      console.error(error.stack);
    }
    process.exit(1);
  } finally {
    await close();
  }
}

main();
