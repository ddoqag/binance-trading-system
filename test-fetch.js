// @ts-check
const { fetchKlines, saveToJSON, saveToCSV } = require('./fetch-market-data');

async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  测试数据获取');
  console.log('═══════════════════════════════════════════════\n');

  try {
    // 只获取 BTCUSDT 1h K线做测试
    const klines = await fetchKlines('BTCUSDT', '1h', 100);

    // 保存到文件
    const timestamp = new Date().toISOString().slice(0, 10);
    saveToJSON(klines, `BTCUSDT-1h-${timestamp}.json`);
    saveToCSV(klines, `BTCUSDT-1h-${timestamp}.csv`);

    console.log('\n✓ 测试完成！');
    console.log('\n接下来可以运行: node main.js 来获取全部数据');

  } catch (error) {
    console.error('\n✗ 测试失败:', error.message);
    process.exit(1);
  }
}

main();
