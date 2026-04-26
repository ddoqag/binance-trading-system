package strategy;

import chan.ChanMarketEngine;
import chan.ChanPricePoint;
import grid.SlantGridEngine;
import plugin.StrategyPlugin;
import state.ChanMarketState;
import state.TradeDirection;
import state.TradeSignal;
import java.util.Set;
import static java.util.Set.of;

public class ChanTrendStrategyPlugin implements StrategyPlugin {
    private static final double SCORE = 92.5;
    private final SlantGridEngine grid = new SlantGridEngine();
    private long kIdx = 0;

    @Override
    public Set<ChanMarketState> getFitStateSet() {
        return of(ChanMarketState.UP_TREND,ChanMarketState.DOWN_TREND,ChanMarketState.DIVERGENCE_TURN);
    }

    @Override public void init(){System.out.println("缠论斜趋势策略初始化");}
    @Override public void onActive(ChanMarketState s){System.out.println("激活趋势策略："+s);}
    @Override public void onInactive(){}
    @Override public void stop(){}
    @Override public String getStrategyName(){return "Chan-Slant-Trend";}
    @Override public double getStrategyScore(){return SCORE;}
    @Override public void onTick(double p, double m, double r, ChanPricePoint pt){kIdx++;}

    @Override
    public TradeSignal getTradeSignal(ChanMarketState state, ChanPricePoint p) {
        ChanMarketEngine eng = new ChanMarketEngine();
        double vol = eng.calcVolatility();
        grid.rebuild(state,p,vol);

        double sup = grid.getNearestSupport(p.centerMid,kIdx);
        double res = grid.getNearestResist(p.centerMid,kIdx);

        switch (state){
            case UP_TREND:
                return new TradeSignal(TradeDirection.LONG,sup,sup*0.997,res);
            case DOWN_TREND:
                return new TradeSignal(TradeDirection.SHORT,res,res*1.003,sup);
            case DIVERGENCE_TURN:
                return new TradeSignal(TradeDirection.CLOSE,p.centerMid,0,0);
            default:
                return TradeSignal.waitSignal();
        }
    }
}
