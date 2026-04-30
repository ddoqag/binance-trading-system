package com.trading.adapter.attribution;

import com.trading.domain.trading.ExecutionAttribution;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Execution Attribution Analyzer - decomposes PnL into components
 */
public class ExecutionAttributionAnalyzer {

    private final Map<String, List<ExecutionAttribution>> attributions = new ConcurrentHashMap<>();
    private final Map<String, AggregatedStats> statsCache = new ConcurrentHashMap<>();

    /**
     * Record an attribution result
     */
    public void record(ExecutionAttribution attribution) {
        if (attribution == null) return;

        String key = attribution.getSignalId();
        attributions.computeIfAbsent(key, k -> new ArrayList<>()).add(attribution);
        statsCache.remove(key); // Invalidate cache
    }

    /**
     * Get aggregated stats for a signal
     */
    public AggregatedStats getStats(String signalId) {
        return statsCache.computeIfAbsent(signalId, this::computeStats);
    }

    private AggregatedStats computeStats(String signalId) {
        List<ExecutionAttribution> list = attributions.getOrDefault(signalId, new ArrayList<>());
        if (list.isEmpty()) {
            return new AggregatedStats();
        }

        double totalPnl = 0;
        double totalSignalAlpha = 0;
        double totalExecutionAlpha = 0;
        double totalSlippage = 0;
        double totalDelayCost = 0;
        double totalMarketImpact = 0;
        double totalAdjustedPnl = 0;

        for (ExecutionAttribution a : list) {
            totalPnl += a.getTotalPnl();
            totalSignalAlpha += a.getSignalAlpha();
            totalExecutionAlpha += a.getExecutionAlpha();
            totalSlippage += a.getSlippage();
            totalDelayCost += a.getDelayCost();
            totalMarketImpact += a.getMarketImpact();
            totalAdjustedPnl += a.getAdjustedPnl();
        }

        int count = list.size();

        return new AggregatedStats(
            count,
            totalPnl,
            totalSignalAlpha / count,
            totalExecutionAlpha / count,
            totalSlippage / count,
            totalDelayCost / count,
            totalMarketImpact / count,
            totalAdjustedPnl,
            calculateSignalQuality(totalSignalAlpha, totalExecutionAlpha)
        );
    }

    private double calculateSignalQuality(double signalAlpha, double executionAlpha) {
        double total = Math.abs(signalAlpha) + Math.abs(executionAlpha);
        if (total < 0.001) return 0.5;
        return Math.abs(signalAlpha) / total;
    }

    /**
     * Get top signals by adjusted PnL
     */
    public List<String> getTopSignalsByAdjustedPnl(int limit) {
        return statsCache.entrySet().stream()
            .sorted((e1, e2) -> Double.compare(e2.getValue().adjustedPnl, e1.getValue().adjustedPnl))
            .limit(limit)
            .map(Map.Entry::getKey)
            .toList();
    }

    /**
     * Get overall aggregate stats
     */
    public AggregatedStats getOverallStats() {
        double totalPnl = 0;
        double totalSignalAlpha = 0;
        double totalExecutionAlpha = 0;
        double totalSlippage = 0;
        double totalDelayCost = 0;
        double totalMarketImpact = 0;

        int count = 0;

        for (List<ExecutionAttribution> list : attributions.values()) {
            for (ExecutionAttribution a : list) {
                totalPnl += a.getTotalPnl();
                totalSignalAlpha += a.getSignalAlpha();
                totalExecutionAlpha += a.getExecutionAlpha();
                totalSlippage += a.getSlippage();
                totalDelayCost += a.getDelayCost();
                totalMarketImpact += a.getMarketImpact();
                count++;
            }
        }

        if (count == 0) {
            return new AggregatedStats();
        }

        return new AggregatedStats(
            count,
            totalPnl,
            totalSignalAlpha / count,
            totalExecutionAlpha / count,
            totalSlippage / count,
            totalDelayCost / count,
            totalMarketImpact / count,
            totalPnl - totalSlippage - totalDelayCost - totalMarketImpact,
            calculateSignalQuality(totalSignalAlpha, totalExecutionAlpha)
        );
    }

    public static class AggregatedStats {
        public final int tradeCount;
        public final double totalPnl;
        public final double avgSignalAlpha;
        public final double avgExecutionAlpha;
        public final double avgSlippage;
        public final double avgDelayCost;
        public final double avgMarketImpact;
        public final double adjustedPnl;
        public final double signalQualityRatio;

        public AggregatedStats() {
            this(0, 0, 0, 0, 0, 0, 0, 0, 0);
        }

        public AggregatedStats(int tradeCount, double totalPnl,
                               double avgSignalAlpha, double avgExecutionAlpha,
                               double avgSlippage, double avgDelayCost,
                               double avgMarketImpact, double adjustedPnl,
                               double signalQualityRatio) {
            this.tradeCount = tradeCount;
            this.totalPnl = totalPnl;
            this.avgSignalAlpha = avgSignalAlpha;
            this.avgExecutionAlpha = avgExecutionAlpha;
            this.avgSlippage = avgSlippage;
            this.avgDelayCost = avgDelayCost;
            this.avgMarketImpact = avgMarketImpact;
            this.adjustedPnl = adjustedPnl;
            this.signalQualityRatio = signalQualityRatio;
        }

        @Override
        public String toString() {
            return String.format(
                "AggregatedStats[n=%d pnl=%.2f signal_q=%.2f exec_q=%.2f slippage=%.2f delay=%.2f impact=%.2f adj_pnl=%.2f]",
                tradeCount, totalPnl, signalQualityRatio, avgExecutionAlpha, avgSlippage, avgDelayCost, avgMarketImpact, adjustedPnl
            );
        }
    }
}