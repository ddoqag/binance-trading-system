const fs = require('fs');
const path = require('path');
const { initDatabase, insertKlines, close } = require('./database');

console.log('═══════════════════════════════════════════════');
console.log('  本地数据导入到 PostgreSQL 数据库');
console.log('═══════════════════════════════════════════════\n');

// 需要导入的数据文件
const FILES_TO_IMPORT = [
  { symbol: 'BTCUSDT', interval: '1h', file: 'BTCUSDT-1h-2026-03-20.json' },
  { symbol: 'BTCUSDT', interval: '15m', file: 'BTCUSDT-15m-2026-03-20.json' }
];

async function readJsonFile(filePath) {
  return new Promise((resolve, reject) => {
    fs.readFile(filePath, 'utf8', (err, data) => {
      if (err) reject(err);
      else resolve(JSON.parse(data));
    });
  });
}

async function importFile(symbol, interval, fileName) {
  const filePath = path.join(__dirname, 'data', fileName);
  console.log(`\n[1/2] 读取文件: ${fileName}`);

  let data;
  try {
    data = await readJsonFile(filePath);
    console.log(`✓ 读取成功: ${data.length} 条记录`);
  } catch (error) {
    console.error(`✗ 读取文件失败: ${error.message}`);
    return 0;
  }

  console.log(`[2/2] 导入到 klines 表...`);

  let importedCount = 0;
  let skippedCount = 0;

  try {
    const result = await insertKlines(symbol, interval, klines);
    importedCount = klines.length;
    console.log(`✓ 导入完成: ${importedCount} 条新增`);
  } catch (error) {
    console.error(`  导入失败:`, error.message);
    skippedCount = klines.length;
  }

  return importedCount;
}

async function main() {
  try {
    // 初始化数据库
    await initDatabase();
    console.log('✓ 数据库初始化成功');

    const results = {
      success: 0,
      failed: 0,
      totalRows: 0
    };

    // 遍历所有要导入的文件
    for (const config of FILES_TO_IMPORT) {
      const imported = await importFile(config.symbol, config.interval, config.file);
      results.success++;
      results.totalRows += imported;
    }

    // 总结
    console.log('\n═══════════════════════════════════════════════');
    console.log('  完成总结');
    console.log('═══════════════════════════════════════════════');
    console.log(`✓ 成功导入: ${results.success} 个文件`);
    console.log(`📊 总数据量: ${results.totalRows} 条`);

  } catch (error) {
    console.error('\n✗ 执行失败:', error.message);
    console.error(error.stack);
  } finally {
    await close();
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error('\n✗ 执行失败:', error);
    process.exit(1);
  });
}

module.exports = {
  importFile,
  main
};
