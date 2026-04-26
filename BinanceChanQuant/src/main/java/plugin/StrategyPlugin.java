package plugin;

import chan.ChanPricePoint;
import state.ChanMarketState;
import state.TradeSignal;
import java.util.Set;

public interface StrategyPlugin {
    void init();
    void onTick(double price, double ma20, double rsi, ChanPricePoint point);
    void onActive(ChanMarketState state);
    void onInactive();
    void stop();
    String getStrategyName();
    Set<ChanMarketState> getFitStateSet();
    double getStrategyScore();
    TradeSignal getTradeSignal(ChanMarketState state, ChanPricePoint point);
}
