// @ts-check
const { SMA, EMA, RSI, MACD, BollingerBands, OBV } = require('technicalindicators');
const { pool } = require('./database');

/**
 * 币安量化交易 - 技术指标计算模块
 */

/**
 * 从数据库获取 K 线数据
 */
async function getKlinesFromDB(symbol, interval, limit = 1000) {
  const result = await pool.query(`
    SELECT open_time, open, high, low, close, volume
    FROM klines
    WHERE symbol = $1 AND interval = $2
    ORDER BY open_time ASC
    LIMIT $3
  `, [symbol, interval, limit]);

  return result.rows;
}

/**
 * 计算移动平均线 (SMA)
 */
function calculateSMA(closePrices, period) {
  return SMA.calculate({ values: closePrices, period });
}

/**
 * 计算指数移动平均线 (EMA)
 */
function calculateEMA(closePrices, period) {
  return EMA.calculate({ values: closePrices, period });
}

/**
 * 计算 RSI (相对强弱指标)
 */
function calculateRSI(closePrices, period = 14) {
  return RSI.calculate({ values: closePrices, period });
}

/**
 * 计算 MACD
 */
function calculateMACD(closePrices, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
  return MACD.calculate({
    values: closePrices,
    fastPeriod,
    slowPeriod,
    signalPeriod,
    SimpleMAOscillator: false,
    SimpleMASignal: false
  });
}

/**
 * 计算布林带
 */
function calculateBollingerBands(closePrices, period = 20, stdDev = 2) {
  return BollingerBands.calculate({
    values: closePrices,
    period,
    stdDev
  });
}

/**
 * 计算 OBV (能量潮)
 */
function calculateOBV(closePrices, volumes) {
  return OBV.calculate({
    close: closePrices,
    volume: volumes
  });
}

/**
 * 计算所有技术指标
 */
async function calculateAllIndicators(symbol, interval) {
  console.log(`\n正在计算 ${symbol} ${interval} 的技术指标...`);

  // 获取 K 线数据
  const klines = await getKlinesFromDB(symbol, interval, 2000);

  if (klines.length === 0) {
    console.log(`⚠ 没有找到 ${symbol} ${interval} 的数据`);
    return [];
  }

  console.log(`✓ 获取到 ${klines.length} 条 K 线数据`);

  // 提取价格和成交量数组
  const closePrices = klines.map(k => parseFloat(k.close));
  const volumes = klines.map(k => parseFloat(k.volume));

  // 计算各项指标
  const ma7 = calculateSMA(closePrices, 7);
  const ma25 = calculateSMA(closePrices, 25);
  const ma99 = calculateSMA(closePrices, 99);
  const rsi14 = calculateRSI(closePrices, 14);
  const macd = calculateMACD(closePrices);
  const bb = calculateBollingerBands(closePrices);
  const obv = calculateOBV(closePrices, volumes);

  // TODO: 这里需要你决定指标保存策略
  // 这是一个关键的决策点：
  // 1. 如何对齐不同指标的时间序列（不同周期有不同的预热期）
  // 2. 是保存所有指标到一行，还是用纵向 KV 结构？
  // 3. 对于缺失的指标值，如何处理？

  // 对齐数据（找到所有指标的公共起始点）
  const maxOffset = Math.max(
    99,  // MA99 需要最多预热
    14,  // RSI
    26,  // MACD slow
    20   // Bollinger
  );

  const indicatorResults = [];

  // 从有完整指标的位置开始
  for (let i = maxOffset; i < klines.length; i++) {
    const kline = klines[i];
    const idx = i - maxOffset;  // 指标数组中的索引

    indicatorResults.push({
      symbol,
      interval,
      openTime: kline.open_time,

      // 移动平均线
      ma7: ma7[idx + (99 - 6)] ? parseFloat(ma7[idx + (99 - 6)]) : null,
      ma25: ma25[idx + (99 - 24)] ? parseFloat(ma25[idx + (99 - 24)]) : null,
      ma99: ma99[idx] ? parseFloat(ma99[idx]) : null,

      // RSI
      rsi14: rsi14[idx + (99 - 13)] ? parseFloat(rsi14[idx + (99 - 13)]) : null,

      // MACD
      macd: macd[idx + (99 - 25)] ? parseFloat(macd[idx + (99 - 25)].MACD) : null,
      macdSignal: macd[idx + (99 - 25)] ? parseFloat(macd[idx + (99 - 25)].signal) : null,
      macdHistogram: macd[idx + (99 - 25)] ? parseFloat(macd[idx + (99 - 25)].histogram) : null,

      // 布林带
      bbUpper: bb[idx + (99 - 19)] ? parseFloat(bb[idx + (99 - 19)].upper) : null,
      bbMiddle: bb[idx + (99 - 19)] ? parseFloat(bb[idx + (99 - 19)].middle) : null,
      bbLower: bb[idx + (99 - 19)] ? parseFloat(bb[idx + (99 - 19)].lower) : null,

      // OBV
      obv: obv[idx + (99 - 1)] ? parseFloat(obv[idx + (99 - 1)]) : null
    });
  }

  console.log(`✓ 计算完成 ${indicatorResults.length} 条指标数据`);
  return indicatorResults;
}

/**
 * 保存技术指标到数据库
 */
async function saveIndicatorsToDB(indicators) {
  if (indicators.length === 0) return;

  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    for (const ind of indicators) {
      await client.query(`
        INSERT INTO technical_indicators (
          symbol, interval, open_time,
          ma7, ma25, ma99,
          rsi14,
          macd, macd_signal, macd_histogram,
          bb_upper, bb_middle, bb_lower,
          obv
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (symbol, interval, open_time) DO UPDATE SET
          ma7 = EXCLUDED.ma7,
          ma25 = EXCLUDED.ma25,
          ma99 = EXCLUDED.ma99,
          rsi14 = EXCLUDED.rsi14,
          macd = EXCLUDED.macd,
          macd_signal = EXCLUDED.macd_signal,
          macd_histogram = EXCLUDED.macd_histogram,
          bb_upper = EXCLUDED.bb_upper,
          bb_middle = EXCLUDED.bb_middle,
          bb_lower = EXCLUDED.bb_lower,
          obv = EXCLUDED.obv
      `, [
        ind.symbol,
        ind.interval,
        ind.openTime,
        ind.ma7,
        ind.ma25,
        ind.ma99,
        ind.rsi14,
        ind.macd,
        ind.macdSignal,
        ind.macdHistogram,
        ind.bbUpper,
        ind.bbMiddle,
        ind.bbLower,
        ind.obv
      ]);
    }

    await client.query('COMMIT');
    console.log(`✓ 成功保存 ${indicators.length} 条指标到数据库`);

  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

/**
 * 计算并保存所有交易对和时间周期的技术指标
 */
async function main() {
  console.log('═══════════════════════════════════════════════');
  console.log('  币安量化交易 - 技术指标计算');
  console.log('═══════════════════════════════════════════════\n');

  const config = {
    symbols: ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT'],
    intervals: ['1h', '4h', '1d']  // 短线用 1h, 中线 4h, 长线 1d
  };

  try {
    for (const symbol of config.symbols) {
      for (const interval of config.intervals) {
        const indicators = await calculateAllIndicators(symbol, interval);
        if (indicators.length > 0) {
          await saveIndicatorsToDB(indicators);
        }
      }
    }

    console.log('\n═══════════════════════════════════════════════');
    console.log('  技术指标计算完成！');
    console.log('═══════════════════════════════════════════════');

  } catch (error) {
    console.error('\n✗ 执行失败:', error);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

// 如果直接运行此文件
if (require.main === module) {
  main();
}

module.exports = {
  calculateSMA,
  calculateEMA,
  calculateRSI,
  calculateMACD,
  calculateBollingerBands,
  calculateOBV,
  calculateAllIndicators,
  saveIndicatorsToDB
};
