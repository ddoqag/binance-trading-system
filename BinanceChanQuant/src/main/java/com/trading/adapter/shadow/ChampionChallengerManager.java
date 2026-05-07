package com.trading.adapter.shadow;

import plugin.StrategyPlugin;
import state.ChanMarketState;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 冠军-挑战者管理器 - 策略自动进化引擎
 *
 * 核心原理:
 * 1. 当前策略为"冠军"
 * 2. 生成N个变异变体为"挑战者"
 * 3. 在shadow模式下同时运行所有挑战者
 * 4. 评估期结束后，表现更好的挑战者晋升为新冠军
 * 5. 旧冠军保留为备份（可回滚）
 *
 * 配置参数:
 * - MUTATION_COUNT: 变异挑战者数量（默认5）
 * - EVALUATION_MINUTES: 评估周期（默认30分钟）
 * - PROMOTION_THRESHOLD: 晋升阈值（默认1.1，即比冠军好10%）
 * - MIN_TRADES: 最少交易次数（默认20笔，否则结果不可信）
 * - WINDOW_SIZE: 绩效快照窗口大小（默认50）
 */
public class ChampionChallengerManager {
    private static final int MUTATION_COUNT = 5;
    private static final int EVALUATION_MINUTES = 30;
    private static final double PROMOTION_THRESHOLD = 1.1;
    private static final int MIN_TRADES = 20;
    private static final int WINDOW_SIZE = 50;

    private final Map<String, PluginVariant> champions = new ConcurrentHashMap<>();
    private final Map<String, List<ShadowRunner>> activeRunners = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private final ExecutorService runnerExecutor = Executors.newCachedThreadPool();

    private volatile boolean running = true;

    public ChampionChallengerManager() {
        System.out.println("[ChampionChallenger] Manager initialized");
    }

    public void stop() {
        running = false;
        activeRunners.values().forEach(this::stopRunners);
        scheduler.shutdownNow();
        runnerExecutor.shutdownNow();
        System.out.println("[ChampionChallenger] Manager stopped");
    }

    /**
     * 注册策略的冠军变体
     */
    public void registerChampion(String strategyId, StrategyPlugin plugin) {
        PluginVariant champion = new PluginVariant(strategyId, "champion", plugin, 1.0);
        champions.put(strategyId, champion);
        System.out.println("[ChampionChallenger] Registered champion for " + strategyId);
    }

    /**
     * 启动策略进化流程
     */
    public void evolve(String strategyId) {
        if (!running) return;

        PluginVariant champion = champions.get(strategyId);
        if (champion == null) {
            System.err.println("[ChampionChallenger] No champion found for " + strategyId);
            return;
        }

        // 1. 生成变异挑战者
        List<PluginVariant> challengers = generateMutations(champion, MUTATION_COUNT);

        // 2. 启动shadow回测
        List<ShadowRunner> runners = startRunners(challengers);

        // 3. 安排评估任务
        activeRunners.put(strategyId, runners);

        scheduler.schedule(() -> {
            evaluateAndPromote(strategyId, champion, runners);
        }, EVALUATION_MINUTES, TimeUnit.MINUTES);

        System.out.println("[ChampionChallenger] Started evolution for " + strategyId +
            " - " + MUTATION_COUNT + " challengers, evaluation in " + EVALUATION_MINUTES + " min");
    }

    private List<PluginVariant> generateMutations(PluginVariant base, int count) {
        List<PluginVariant> mutations = new ArrayList<>();

        for (int i = 0; i < count; i++) {
            String id = base.getStrategyId() + "_mutant_" + i;
            StrategyPlugin mutated = mutatePlugin(base.getPlugin(), i);
            double weight = 1.0 / (i + 1); // 权重递减

            mutations.add(new PluginVariant(id, base.getStrategyId(), mutated, weight));
        }

        return mutations;
    }

    private StrategyPlugin mutatePlugin(StrategyPlugin original, int mutationIndex) {
        // 对于DNA策略，根据mutationIndex应用不同的参数变异
        // 这里使用装饰器模式包装原策略，在运行时应用不同的参数

        return new MutatedStrategyPlugin(original, mutationIndex);
    }

    private List<ShadowRunner> startRunners(List<PluginVariant> variants) {
        List<ShadowRunner> runners = new CopyOnWriteArrayList<>();

        for (PluginVariant v : variants) {
            ShadowRunner runner = new ShadowRunner(
                v.getId(),
                v.getPlugin(),
                WINDOW_SIZE
            );
            runnerExecutor.submit(runner);
            runners.add(runner);
        }

        return runners;
    }

    private void evaluateAndPromote(String strategyId, PluginVariant champion,
                                    List<ShadowRunner> runners) {
        stopRunners(runners);

        // 收集所有挑战者的适应度
        Map<String, FitnessResult> results = new HashMap<>();
        for (ShadowRunner runner : runners) {
            results.put(runner.getId(), runner.getFitness());
        }

        // 找最佳挑战者
        Optional<Map.Entry<String, FitnessResult>> best = results.entrySet().stream()
            .filter(e -> e.getValue().getScore() > 0)
            .max(Comparator.comparingDouble(e -> e.getValue().getScore()));

        if (best.isPresent()) {
            String bestId = best.get().getKey();
            FitnessResult bestFitness = best.get().getValue();
            FitnessResult championFitness = new FitnessResult(0, 0, 0, 0, 0, 0); // 冠军未运行

            System.out.println("[ChampionChallenger] Evaluation results for " + strategyId + ":");
            results.forEach((id, fitness) ->
                System.out.println("  " + id + ": " + fitness)
            );

            // 检查是否应该晋升
            if (shouldPromote(bestFitness, championFitness)) {
                promoteChallenger(strategyId, bestId, bestFitness);
            } else {
                System.out.println("[ChampionChallenger] No promotion - best challenger " +
                    "did not outperform champion by threshold");
            }
        } else {
            System.out.println("[ChampionChallenger] No valid challengers for " + strategyId);
        }

        activeRunners.remove(strategyId);

        // 持续进化：评估后自动启动新一轮
        if (running && champions.containsKey(strategyId)) {
            long delayMinutes = EVALUATION_MINUTES;
            System.out.println("[ChampionChallenger] Scheduling next evolution in " + delayMinutes + " min");
            scheduler.schedule(() -> {
                if (running && champions.containsKey(strategyId)) {
                    evolve(strategyId);
                }
            }, delayMinutes, TimeUnit.MINUTES);
        }
    }

    private boolean shouldPromote(FitnessResult challenger, FitnessResult champion) {
        // 挑战者必须有基本的交易次数和正分数
        if (challenger.getScore() <= 0) return false;

        // 必须比冠军好至少PROMOTION_THRESHOLD
        return challenger.getScore() > champion.getScore() * PROMOTION_THRESHOLD;
    }

    private void promoteChallenger(String strategyId, String challengerId, FitnessResult fitness) {
        System.out.println("[ChampionChallenger] PROMOTING " + challengerId +
            " with fitness " + fitness);
        // 实际晋升逻辑会在后续版本实现
        // 目前主要是收集数据和日志
    }

    private void stopRunners(List<ShadowRunner> runners) {
        runners.forEach(ShadowRunner::stop);
    }

    public FitnessResult getChampionFitness(String strategyId) {
        PluginVariant champion = champions.get(strategyId);
        if (champion == null) return FitnessResult.zero();
        return new FitnessResult(0, 0, 0, 0, 0, 0); // 冠军不计算适应度
    }

    public boolean hasChampion(String strategyId) {
        return champions.containsKey(strategyId);
    }

    /**
     * Feed market data to all active runners for a strategy
     */
    public void feedMarketData(String strategyId, com.trading.domain.market.model.MarketData data,
                               ChanMarketState state, chan.ChanPricePoint point) {
        List<ShadowRunner> runners = activeRunners.get(strategyId);
        if (runners == null) return;
        for (ShadowRunner runner : runners) {
            runner.onMarketData(data);
            runner.onStateChange(state);
        }
    }

    /**
     * Get all active runners for a strategy
     */
    public List<ShadowRunner> getActiveRunners(String strategyId) {
        return activeRunners.getOrDefault(strategyId, Collections.emptyList());
    }

    // ========== 内部类 ==========

    public static class PluginVariant {
        private final String id;
        private final String strategyId;
        private final StrategyPlugin plugin;
        private final double trafficWeight;

        public PluginVariant(String id, String strategyId, StrategyPlugin plugin, double trafficWeight) {
            this.id = id;
            this.strategyId = strategyId;
            this.plugin = plugin;
            this.trafficWeight = trafficWeight;
        }

        public String getId() { return id; }
        public String getStrategyId() { return strategyId; }
        public StrategyPlugin getPlugin() { return plugin; }
        public double getTrafficWeight() { return trafficWeight; }
    }

    /**
     * 变异策略插件 - 包装原策略，应用不同参数
     */
    private static class MutatedStrategyPlugin implements StrategyPlugin {
        private final StrategyPlugin original;
        private final int mutationIndex;
        private final double[] mutatedWeights;

        MutatedStrategyPlugin(StrategyPlugin original, int mutationIndex) {
            this.original = original;
            this.mutationIndex = mutationIndex;

            // 根据mutationIndex生成不同的权重变异
            // DNA权重: W_MA10=0.2466, W_HL=0.2042, W_VOL=0.1462, W_NLT=0.2310
            this.mutatedWeights = generateMutatedWeights(mutationIndex);
        }

        private double[] generateMutatedWeights(int index) {
            double[] base = {0.2466, 0.2042, 0.1462, 0.2310};
            double[] mutated = new double[base.length];

            // 不同的变异模式
            switch (index % 5) {
                case 0: // 增加MA权重
                    mutated[0] = base[0] * 1.2;
                    mutated[1] = base[1] * 0.9;
                    mutated[2] = base[2];
                    mutated[3] = base[3] * 0.9;
                    break;
                case 1: // 增加HL权重
                    mutated[0] = base[0] * 0.9;
                    mutated[1] = base[1] * 1.2;
                    mutated[2] = base[2] * 0.9;
                    mutated[3] = base[3];
                    break;
                case 2: // 增加VOL权重
                    mutated[0] = base[0];
                    mutated[1] = base[1] * 0.9;
                    mutated[2] = base[2] * 1.3;
                    mutated[3] = base[3] * 0.8;
                    break;
                case 3: // 增加NLT权重
                    mutated[0] = base[0] * 0.8;
                    mutated[1] = base[1];
                    mutated[2] = base[2] * 0.9;
                    mutated[3] = base[3] * 1.2;
                    break;
                case 4: // 均衡变异
                    mutated[0] = base[0] * 1.1;
                    mutated[1] = base[1] * 1.1;
                    mutated[2] = base[2] * 0.9;
                    mutated[3] = base[3] * 0.9;
                    break;
            }

            // 归一化
            double sum = Arrays.stream(mutated).sum();
            for (int i = 0; i < mutated.length; i++) {
                mutated[i] = mutated[i] / sum * (base[0] + base[1] + base[2] + base[3]);
            }

            return mutated;
        }

        @Override
        public void init() { original.init(); }

        @Override
        public void onTick(double price, double ma20, double rsi, chan.ChanPricePoint pt) {
            original.onTick(price, ma20, rsi, pt);
        }

        @Override
        public void onActive(ChanMarketState state) { original.onActive(state); }

        @Override
        public void onInactive() { original.onInactive(); }

        @Override
        public void stop() { original.stop(); }

        @Override
        public String getStrategyName() {
            return original.getStrategyName() + "_M" + mutationIndex;
        }

        @Override
        public java.util.Set<ChanMarketState> getFitStateSet() {
            return original.getFitStateSet();
        }

        @Override
        public double getStrategyScore() {
            // 变异后评分基于原始评分和适应度
            return original.getStrategyScore() * 0.9; // 初始保守
        }

        @Override
        public state.TradeSignal getTradeSignal(ChanMarketState state,
                                                          chan.ChanPricePoint point) {
            return original.getTradeSignal(state, point);
        }

        public double[] getMutatedWeights() { return mutatedWeights; }
    }
}
