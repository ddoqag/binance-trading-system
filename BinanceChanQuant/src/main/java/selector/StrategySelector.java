package selector;

import plugin.StrategyPlugin;
import state.ChanMarketState;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

public class StrategySelector {
    private final List<StrategyPlugin> pool = new ArrayList<>();
    private StrategyPlugin active;
    private final StrategyScoreManager scoreMgr = new StrategyScoreManager();

    public void registerStrategy(StrategyPlugin p){
        pool.add(p);
        p.init();
    }

    public void selectBest(ChanMarketState state){
        if(pool.isEmpty()) return;
        List<StrategyPlugin> list = pool.stream()
                .filter(s->s.getFitStateSet().contains(state))
                .collect(Collectors.toList());
        if(list.isEmpty()) return;

        StrategyPlugin best = list.stream()
                .max(Comparator.comparingDouble(s->scoreMgr.getScore(s.getStrategyName())))
                .get();

        if(best!=active){
            if(active!=null) active.onInactive();
            active=best;
            active.onActive(state);
        }
    }

    public StrategyPlugin getActive(){return active;}
    public StrategyScoreManager getScoreMgr(){return scoreMgr;}
}
