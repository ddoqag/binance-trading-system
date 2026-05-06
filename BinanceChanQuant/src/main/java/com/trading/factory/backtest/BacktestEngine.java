package com.trading.factory.backtest;

import com.trading.factory.model.BacktestResult;
import com.trading.factory.model.StrategyGenome;
import com.trading.factory.model.StrategyMetrics;

import java.util.ArrayList;
import java.util.List;

/**
 * Backtest Engine - Runs backtest on historical data with train/test split
 */
public class BacktestEngine {

    private static final double TRAIN_RATIO = 0.7;
    private static final int MIN_TRADES = 5;

    private final HistoricalDataProvider dataProvider;

    public BacktestEngine(HistoricalDataProvider dataProvider) {
        this.dataProvider = dataProvider;
    }

    /**
     * Run backtest on genome
     */
    public BacktestResult backtest(StrategyGenome genome) {
        long startTime = System.currentTimeMillis();

        HistoricalDataProvider.DataSplit split = dataProvider.splitData(TRAIN_RATIO);

        List<BacktestResult.TradeRecord> allTrades = new ArrayList<>();
        StrategyMetrics trainMetrics = runOnData(genome, split.train(), allTrades);
        StrategyMetrics testMetrics = runOnData(genome, split.test(), allTrades);

        long duration = System.currentTimeMillis() - startTime;

        return BacktestResult.builder()
                .genome(genome)
                .trainMetrics(trainMetrics)
                .testMetrics(testMetrics)
                .backtestDurationMs(duration)
                .trades(allTrades)
                .build();
    }

    /**
     * Run on single dataset, return metrics
     */
    private StrategyMetrics runOnData(StrategyGenome genome, List<HistoricalDataProvider.OHLCV> bars,
                                       List<BacktestResult.TradeRecord> tradeCollector) {
        if (bars.size() < 20) return StrategyMetrics.zero();

        List<Double> equityCurve = new ArrayList<>();
        List<Double> returns = new ArrayList<>();
        List<Long> tradeEntryTimes = new ArrayList<>();
        List<Double> tradeEntryPrices = new ArrayList<>();

        double equity = 0;
        int wins = 0;
        int losses = 0;
        double totalWin = 0;
        double totalLoss = 0;

        boolean inPosition = false;
        double entryPrice = 0;
        long entryTime = 0;

        double maShort = genome.getParameter("maShort") != null ?
                genome.getParameter("maShort") : 20;
        double maLong = genome.getParameter("maLong") != null ?
                genome.getParameter("maLong") : 60;
        double atrMultiplier = genome.getParameter("atrMultiplier") != null ?
                genome.getParameter("atrMultiplier") : 2.0;

        // Calculate MAs
        List<Double> maSValues = calculateMA(bars, (int) maShort);
        List<Double> maLValues = calculateMA(bars, (int) maLong);

        for (int i = (int) Math.max(maLong, maShort); i < bars.size(); i++) {
            HistoricalDataProvider.OHLCV bar = bars.get(i);
            double price = bar.close();

            // Simple MA crossover logic
            double maS = maSValues.get(i - (int) maShort);
            double maL = maLValues.get(i - (int) maLong);

            if (maS == 0 || maL == 0) continue;

            double atr = calculateATR(bars, i, 14);

            if (!inPosition && maS > maL) {
                // Long signal
                entryPrice = price;
                entryTime = bar.timestamp();
                inPosition = true;
            } else if (inPosition && maS < maL) {
                // Exit signal
                double pnl = (price - entryPrice) / entryPrice;
                equity += pnl;

                tradeCollector.add(new BacktestResult.TradeRecord(
                        entryTime, entryPrice, price, pnl
                ));

                if (pnl > 0) { wins++; totalWin += pnl; }
                else { losses++; totalLoss += Math.abs(pnl); }

                returns.add(pnl);
                inPosition = false;
            }

            equityCurve.add(equity);
        }

        if (tradeCollector.size() < MIN_TRADES) {
            return StrategyMetrics.zero();
        }

        return calculateMetrics(equityCurve, returns, wins, losses, totalWin, totalLoss);
    }

    private List<Double> calculateMA(List<HistoricalDataProvider.OHLCV> bars, int period) {
        List<Double> ma = new ArrayList<>();
        for (int i = 0; i < bars.size(); i++) {
            if (i < period - 1) {
                ma.add(0.0);
            } else {
                double sum = 0;
                for (int j = i - period + 1; j <= i; j++) {
                    sum += bars.get(j).close();
                }
                ma.add(sum / period);
            }
        }
        return ma;
    }

    private double calculateATR(List<HistoricalDataProvider.OHLCV> bars, int current, int period) {
        if (current < period) return 0;
        double sum = 0;
        for (int i = current - period + 1; i <= current; i++) {
            double tr = Math.max(
                    bars.get(i).high() - bars.get(i).low(),
                    Math.max(
                            Math.abs(bars.get(i).high() - bars.get(i - 1).close()),
                            Math.abs(bars.get(i).low() - bars.get(i - 1).close())
                    )
            );
            sum += tr;
        }
        return sum / period;
    }

    private StrategyMetrics calculateMetrics(List<Double> equityCurve,
                                             List<Double> returns,
                                             int wins, int losses,
                                             double totalWin, double totalLoss) {

        if (returns.isEmpty()) return StrategyMetrics.zero();

        // Sharpe ratio (simplified)
        double avgReturn = returns.stream().mapToDouble(Double::doubleValue).average().orElse(0);
        double stdReturn = Math.sqrt(returns.stream()
                .mapToDouble(r -> Math.pow(r - avgReturn, 2))
                .sum() / returns.size());
        double sharpe = stdReturn > 0 ? (avgReturn / stdReturn) * Math.sqrt(252) : 0;

        // Max drawdown
        double peak = 0;
        double maxDD = 0;
        for (double eq : equityCurve) {
            if (eq > peak) peak = eq;
            double dd = peak - eq;
            if (dd > maxDD) maxDD = dd;
        }

        // Win rate
        int total = wins + losses;
        double winRate = total > 0 ? (double) wins / total : 0;

        // Profit factor
        double profitFactor = totalLoss > 0 ? totalWin / totalLoss : 0;

        // Total return
        double totalReturn = equityCurve.isEmpty() ? 0 :
                equityCurve.get(equityCurve.size() - 1);

        return StrategyMetrics.builder()
                .sharpe(sharpe)
                .maxDrawdown(maxDD)
                .winRate(winRate)
                .profitFactor(profitFactor)
                .tradesCount(total)
                .totalReturn(totalReturn)
                .build();
    }

    /**
     * Walk-forward analysis
     */
    public List<BacktestResult> walkForward(StrategyGenome genome,
                                             int windowDays, int stepDays) {
        List<BacktestResult> results = new ArrayList<>();
        List<HistoricalDataProvider.OHLCV> allBars = dataProvider.getBars();

        int windowSize = windowDays * 24; // rough estimate
        int stepSize = stepDays * 24;

        for (int start = 0; start + windowSize < allBars.size(); start += stepSize) {
            int end = Math.min(start + windowSize, allBars.size());
            List<HistoricalDataProvider.OHLCV> windowBars = allBars.subList(start, end);

            HistoricalDataProvider.DataSplit split = splitData(windowBars, 0.7);

            List<BacktestResult.TradeRecord> trades = new ArrayList<>();
            StrategyMetrics trainM = runOnData(genome, split.train(), trades);
            StrategyMetrics testM = runOnData(genome, split.test(), trades);

            results.add(BacktestResult.builder()
                    .genome(genome)
                    .trainMetrics(trainM)
                    .testMetrics(testM)
                    .trades(trades)
                    .build());
        }

        return results;
    }

    private HistoricalDataProvider.DataSplit splitData(List<HistoricalDataProvider.OHLCV> bars, double ratio) {
        int split = (int) (bars.size() * ratio);
        return new HistoricalDataProvider.DataSplit(
                bars.subList(0, split),
                bars.subList(split, bars.size())
        );
    }
}