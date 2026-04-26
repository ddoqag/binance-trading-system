package chan;

import state.ChanMarketState;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

public class ChanMarketEngine {
    private final List<KLine> kList = new ArrayList<>();
    private static final int MAX_K = 120;

    private final List<FenxingType> fenxingList = new ArrayList<>();
    private final List<Bi> biList = new ArrayList<>();
    private final List<XianDuan> xdList = new ArrayList<>();
    private final List<ZhongShu> zsList = new ArrayList<>();

    private ChanMarketState curState = ChanMarketState.CONSOLIDATION;
    private final ChanPricePoint pricePoint = new ChanPricePoint();

    public void feedPrice(double price, long time) {
        KLine k = new KLine(price, price, price, price, time);
        kList.add(k);
        if (kList.size() > MAX_K) kList.remove(0);
        calcFenxing();
        judgeMarketState();
        fillPricePoint();
    }

    private void calcFenxing() {
        fenxingList.clear();
        for (int i = 2; i < kList.size() - 2; i++) {
            KLine k1 = kList.get(i-2);
            KLine k2 = kList.get(i-1);
            KLine k3 = kList.get(i);
            KLine k4 = kList.get(i+1);
            KLine k5 = kList.get(i+2);

            boolean top = k3.high > k1.high && k3.high > k2.high
                    && k3.high > k4.high && k3.high > k5.high;
            boolean bottom = k3.low < k1.low && k3.low < k2.low
                    && k3.low < k4.low && k3.low < k5.low;

            if (top) fenxingList.add(FenxingType.TOP_FENXING);
            else if (bottom) fenxingList.add(FenxingType.BOTTOM_FENXING);
            else fenxingList.add(FenxingType.NONE);
        }
    }

    private void judgeMarketState() {
        if(kList.size()<20) return;
        double max = kList.stream().mapToDouble(k->k.high).max().orElse(0);
        double min = kList.stream().mapToDouble(k->k.low).min().orElse(0);
        double last = kList.get(kList.size()-1).close;
        double range = (max - min) / min;
        double trend = (last - min) / (max - min);

        if (range < 0.015) {
            curState = ChanMarketState.CONSOLIDATION;
        } else if (trend > 0.6) {
            curState = ChanMarketState.UP_TREND;
        } else if (trend < 0.4) {
            curState = ChanMarketState.DOWN_TREND;
        } else {
            curState = ChanMarketState.DIVERGENCE_TURN;
        }
    }

    private void fillPricePoint() {
        if(kList.isEmpty()) return;
        double max = kList.stream().mapToDouble(k->k.high).max().orElse(0);
        double min = kList.stream().mapToDouble(k->k.low).min().orElse(0);
        double mid = (max + min) / 2;

        pricePoint.centerUp = max;
        pricePoint.centerDown = min;
        pricePoint.centerMid = mid;
        pricePoint.curPenHigh = max;
        pricePoint.curPenLow = min;
        pricePoint.divergencePrice = mid;
    }

    public double calcVolatility() {
        if (kList.size() < 20) return 1.0;
        double sumRange = 0.0;
        for (KLine k : kList) {
            double range = (k.high - k.low) / k.close;
            sumRange += range;
        }
        double avgRange = sumRange / kList.size();
        return Math.max(0.6, avgRange * 120);
    }

    public ChanMarketState getCurrentState(){return curState;}
    public ChanPricePoint getPricePoint(){return pricePoint;}
}
