package strategy;

import state.ChanMarketState;
import chan.ChanPricePoint;
import state.TradeDirection;
import state.TradeSignal;
import plugin.StrategyPlugin;

import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

import static java.util.Set.of;

/**
 * DNA策略插件 - 通达信公式转换
 *
 * 核心因子:
 * - MA10_RATIO: 价格相对MA10偏离
 * - HL_RATIO:   日内波动率
 * - VOLATILITY_5: 5日波动率
 * - NONLINEAR_TREND: 非线性趋势 (EMA5 - EMA20)
 *
 * 权重: MA10*0.2466 + HL*0.2042 + VOL*0.1462 + NLT*0.2310
 *
 * 风险管理:
 * - 止损: 9.7%
 * - 止盈: 24.4%
 * - 最大持仓: 44根K线
 */
public class DNAStrategyPlugin implements StrategyPlugin {

    // 因子权重
    private static final double W_MA10 = 0.2466;
    private static final double W_HL = 0.2042;
    private static final double W_VOL = 0.1462;
    private static final double W_NLT = 0.2310;

    // 信号阈值
    private static final double BUY_THRESHOLD = 15.0;
    private static final double SELL_THRESHOLD = 0.0;

    // 风险管理
    private static final double STOP_LOSS_RATE = 0.097;  // 9.7%
    private static final double TAKE_PROFIT_RATE = 0.244; // 24.4%
    private static final int MAX_HOLD_BARS = 44;

    private final AtomicLong tradeBars = new AtomicLong(0);
    private final AtomicReference<Double> lastBuyPrice = new AtomicReference<>(0.0);
    private final AtomicReference<Double> lastBuyScore = new AtomicReference<>(0.0);

    // 历史数据计算用
    private double[] prices = new double[60];
    private int priceIdx = 0;
    private int priceCount = 0;

    @Override
    public Set<ChanMarketState> getFitStateSet() {
        return of(ChanMarketState.CONSOLIDATION, ChanMarketState.UP_TREND,
                  ChanMarketState.DOWN_TREND, ChanMarketState.DIVERGENCE_TURN);
    }

    @Override
    public void init() {
        System.out.println("[DNA] DNA策略插件初始化");
    }

    @Override
    public void onActive(ChanMarketState state) {
        System.out.println("[DNA] 策略激活: " + state);
    }

    @Override
    public void onInactive() {
        System.out.println("[DNA] 策略切换至非活跃");
    }

    @Override
    public void stop() {
        System.out.println("[DNA] 策略停止");
    }

    @Override
    public String getStrategyName() {
        return "DNA_BALANCED";
    }

    @Override
    public double getStrategyScore() {
        return 92.5;
    }

    @Override
    public void onTick(double price, double ma20, double rsi, ChanPricePoint pt) {
        // 更新价格数组
        prices[priceIdx % 60] = price;
        priceIdx++;
        if (priceCount < 60) priceCount++;
    }

    @Override
    public TradeSignal getTradeSignal(ChanMarketState state, ChanPricePoint point) {
        if (priceCount < 25) {
            return TradeSignal.waitSignal();
        }

        // 计算因子
        double ma10 = calcMA(10);
        double ma5 = calcMA(5);
        double ema5 = calcEMA(5, 5);
        double ema20 = calcEMA(20, 20);
        double std5 = calcSTD(5);
        double prevClose = prices[(priceIdx - 2 + 60) % 60];
        double high = prices[(priceIdx - 2 + 60) % 60];
        double low = prices[(priceIdx - 2 + 60) % 60];

        // 扫描最高最低价
        for (int i = 0; i < priceCount && i < 20; i++) {
            double p = prices[(priceIdx - i - 1 + 60) % 60];
            if (p > high) high = p;
            if (p < low) low = p;
        }

        double curPrice = prices[(priceIdx - 1 + 60) % 60];

        // 计算各因子得分
        double ma10Ratio = (curPrice - ma10) / ma10 * 100;
        double ma10Score = calcMA10Score(ma10Ratio);

        double hlRatio = (high - low) / prevClose * 100;
        double hlScore = calcHLScore(hlRatio);

        double volScore = calcVolScore(std5);

        double nonlinearTrend = ema5 - ema20;
        double nltScore = calcNLTScore(nonlinearTrend);

        // 综合得分
        double totalScore = ma10Score * W_MA10 + hlScore * W_HL + volScore * W_VOL + nltScore * W_NLT;

        // 检查持仓状态
        long bars = tradeBars.get();
        Double lastBuy = lastBuyPrice.get();
        Double lastScore = lastBuyScore.get();

        // 止损/止盈/超期检查
        if (lastBuy > 0) {
            // 止损检查
            if (curPrice < lastBuy * (1 - STOP_LOSS_RATE)) {
                tradeBars.set(0);
                lastBuyPrice.set(0.0);
                System.out.printf("[DNA] 止损触发: 买入价=%.2f, 当前价=%.2f, 损失=%.2f%%%n",
                    lastBuy, curPrice, (1 - curPrice/lastBuy) * 100);
                return new TradeSignal(TradeDirection.CLOSE, curPrice, 0, 0);
            }
            // 止盈检查
            if (curPrice > lastBuy * (1 + TAKE_PROFIT_RATE)) {
                tradeBars.set(0);
                lastBuyPrice.set(0.0);
                System.out.printf("[DNA] 止盈触发: 买入价=%.2f, 当前价=%.2f, 盈利=%.2f%%%n",
                    lastBuy, curPrice, (curPrice/lastBuy - 1) * 100);
                return new TradeSignal(TradeDirection.CLOSE, curPrice, 0, 0);
            }
            // 超期检查
            if (bars >= MAX_HOLD_BARS) {
                tradeBars.set(0);
                lastBuyPrice.set(0.0);
                System.out.printf("[DNA] 超期强制平仓: 持仓%d根K线%n", bars);
                return new TradeSignal(TradeDirection.CLOSE, curPrice, 0, 0);
            }
        }

        // 买卖信号
        if (totalScore > BUY_THRESHOLD && lastBuy <= 0) {
            tradeBars.set(0);
            lastBuyPrice.set(curPrice);
            lastBuyScore.set(totalScore);
            double stopLoss = curPrice * (1 - STOP_LOSS_RATE);
            double takeProfit = curPrice * (1 + TAKE_PROFIT_RATE);
            System.out.printf("[DNA] 买入信号: 得分=%.2f, 价格=%.2f, 止损=%.2f, 止盈=%.2f%n",
                totalScore, curPrice, stopLoss, takeProfit);
            return new TradeSignal(TradeDirection.LONG, curPrice, stopLoss, takeProfit);
        }

        if (totalScore < SELL_THRESHOLD && lastBuy > 0) {
            tradeBars.set(0);
            lastBuyPrice.set(0.0);
            System.out.printf("[DNA] 卖出信号: 得分=%.2f, 价格=%.2f%n", totalScore, curPrice);
            return new TradeSignal(TradeDirection.CLOSE, curPrice, 0, 0);
        }

        // 持仓计数
        if (lastBuy > 0) {
            tradeBars.incrementAndGet();
        }

        return TradeSignal.waitSignal();
    }

    // 计算简单移动平均
    private double calcMA(int period) {
        if (priceCount < period) return 0;
        double sum = 0;
        for (int i = 0; i < period; i++) {
            sum += prices[(priceIdx - i - 1 + 60) % 60];
        }
        return sum / period;
    }

    // 计算EMA (简化版)
    private double calcEMA(int period, int lookback) {
        if (priceCount < period + lookback) return 0;
        double multiplier = 2.0 / (period + 1);
        double ema = calcMA(period);
        for (int i = period; i < lookback; i++) {
            double price = prices[(priceIdx - i - 1 + 60) % 60];
            ema = price * multiplier + ema * (1 - multiplier);
        }
        return ema;
    }

    // 计算标准差
    private double calcSTD(int period) {
        if (priceCount < period) return 0;
        double sum = 0;
        double sumSq = 0;
        for (int i = 0; i < period; i++) {
            double p = prices[(priceIdx - i - 1 + 60) % 60];
            sum += p;
            sumSq += p * p;
        }
        double mean = sum / period;
        double variance = (sumSq / period) - (mean * mean);
        return Math.sqrt(Math.max(variance, 0));
    }

    // MA10比率得分
    private double calcMA10Score(double ratio) {
        if (ratio > 2) return 25;
        if (ratio > 0) return 15;
        if (ratio > -2) return 5;
        return -15;
    }

    // 高低价比率得分
    private double calcHLScore(double ratio) {
        if (ratio > 5) return 20;
        if (ratio > 3) return 10;
        if (ratio > 1) return 5;
        return -5;
    }

    // 波动率得分
    private double calcVolScore(double std5) {
        if (std5 > 0.02) return 15;
        if (std5 > 0.01) return 10;
        return 5;
    }

    // 非线性趋势得分
    private double calcNLTScore(double nlt) {
        if (nlt > 0.02) return 23;
        if (nlt > 0) return 13;
        if (nlt > -0.01) return 5;
        return -10;
    }
}