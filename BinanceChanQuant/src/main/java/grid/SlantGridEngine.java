package grid;

import chan.ChanPricePoint;
import state.ChanMarketState;
import java.util.ArrayList;
import java.util.List;

public class SlantGridEngine {
    private static final int GRID_COUNT = 8;
    private static final double BASE_CHANNEL_RATIO = 0.007;
    private static final double DIVERGENCE_GRID_MULTIPLIER = 0.4;

    private final List<SlantGridLine> supportLines = new ArrayList<>();
    private final List<SlantGridLine> resistLines = new ArrayList<>();
    private double trendSlope = 0.0;
    private double baseCenterPrice = 0.0;
    private ChanMarketState lastState = null;

    public void rebuild(ChanMarketState state, ChanPricePoint point, double volatility) {
        supportLines.clear();
        resistLines.clear();
        baseCenterPrice = point.centerMid;
        double baseGridStep = BASE_CHANNEL_RATIO * volatility;
        double gridStep = baseGridStep;

        switch (state) {
            case UP_TREND:
                // 动态斜率阻尼: 使用max(25, ATR*1000)替代固定25.0
                double dampingFactor = Math.max(25.0, volatility * 1000);
                trendSlope = (point.curPenHigh - point.centerDown) / dampingFactor;
                break;
            case DOWN_TREND:
                dampingFactor = Math.max(25.0, volatility * 1000);
                double rawSlope = (point.curPenLow - point.centerUp) / dampingFactor;
                // 确保下降趋势斜率永远为负，掩盖数据异常
                trendSlope = Math.min(rawSlope, -0.001); // 最小斜率防止零斜率
                break;
            case DIVERGENCE_TURN:
                // 背驰状态: 网格加密，仅在状态变化时应用乘法，避免累积衰减
                if (lastState != state) {
                    gridStep = baseGridStep * DIVERGENCE_GRID_MULTIPLIER;
                }
                trendSlope = 0;
                break;
            default:
                // CONSOLIDATION: 水平网格
                trendSlope = 0;
        }

        lastState = state;

        for (int i = 1; i <= GRID_COUNT; i++) {
            SlantGridLine line = new SlantGridLine();
            line.index = i;
            line.slope = trendSlope;
            line.basePrice = baseCenterPrice * (1 - gridStep * i);
            supportLines.add(line);
        }
        for (int i = 1; i <= GRID_COUNT; i++) {
            SlantGridLine line = new SlantGridLine();
            line.index = i;
            line.slope = trendSlope;
            line.basePrice = baseCenterPrice * (1 + gridStep * i);
            resistLines.add(line);
        }
    }

    public double getNearestSupport(double nowPrice, long kIdx) {
        double best = 0.0;
        for (SlantGridLine line : supportLines) {
            double p = line.getNowPrice(kIdx);
            if (p < nowPrice && p > best) best = p;
        }
        return best;
    }

    public double getNearestResist(double nowPrice, long kIdx) {
        double best = Double.MAX_VALUE;
        for (SlantGridLine line : resistLines) {
            double p = line.getNowPrice(kIdx);
            if (p > nowPrice && p < best) best = p;
        }
        return best;
    }
}
