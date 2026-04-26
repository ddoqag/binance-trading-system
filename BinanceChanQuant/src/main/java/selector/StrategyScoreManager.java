package selector;

import java.util.HashMap;
import java.util.Map;

public class StrategyScoreManager {
    private final Map<String, StrategyPerformance> map = new HashMap<>();

    public void recordTrade(String name, boolean win, double profit){
        StrategyPerformance perf = map.getOrDefault(name,new StrategyPerformance());
        perf.totalTrade++;
        if(win) perf.winTrade++;
        perf.totalProfit += profit;
        perf.winRate = perf.totalTrade==0?0:(double)perf.winTrade/perf.totalTrade;
        perf.maxDrawDown = Math.min(perf.maxDrawDown,profit);
        perf.score = perf.winRate*60 + Math.max(0,perf.totalProfit)*30 - Math.abs(perf.maxDrawDown)*10;
        map.put(name,perf);
    }

    public double getScore(String name){
        StrategyPerformance p = map.get(name);
        return p==null?50.0:p.score;
    }
}
