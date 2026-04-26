package grid;

import chan.ChanPricePoint;
import state.ChanMarketState;
import java.util.ArrayList;
import java.util.List;

public class SlantGridEngine {
    private static final int GRID_COUNT = 8;
    private static final double BASE_CHANNEL_RATIO = 0.007;

    private final List<SlantGridLine> supportLines = new ArrayList<>();
    private final List<SlantGridLine> resistLines = new ArrayList<>();
    private double trendSlope = 0.0;
    private double baseCenterPrice = 0.0;

    public void rebuild(ChanMarketState state, ChanPricePoint point, double volatility) {
        supportLines.clear();
        resistLines.clear();
        baseCenterPrice = point.centerMid;
        double gridStep = BASE_CHANNEL_RATIO * volatility;

        switch (state) {
            case UP_TREND:
                trendSlope = (point.curPenHigh - point.centerDown) / 25.0;
                break;
            case DOWN_TREND:
                trendSlope = -Math.abs((point.curPenLow - point.centerUp) / 25.0);
                break;
            case DIVERGENCE_TURN:
                gridStep *= 0.4;
                trendSlope = 0;
                break;
            default:
                trendSlope = 0;
        }

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
