package selector;

import plugin.StrategyPlugin;
import state.ChanMarketState;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * StrategySelector TDD Tests
 */
class StrategySelectorTest {

    private StrategySelector selector;

    @BeforeEach
    void setUp() {
        selector = new StrategySelector();
    }

    @Test
    @DisplayName("Should return null when no strategies registered")
    void shouldReturnNullWhenNoStrategies() {
        selector.selectBest(ChanMarketState.UP_TREND);
        assertNull(selector.getActive());
    }

    @Test
    @DisplayName("Should register strategy but not select until selectBest called")
    void shouldRegisterAndInitStrategy() {
        StrategyPlugin mockPlugin = mock(StrategyPlugin.class);
        when(mockPlugin.getStrategyName()).thenReturn("test-strategy");
        when(mockPlugin.getFitStateSet()).thenReturn(Set.of(ChanMarketState.UP_TREND));

        selector.registerStrategy(mockPlugin);

        verify(mockPlugin).init();
        // getActive returns null until selectBest is called
        assertNull(selector.getActive());
    }

    @Test
    @DisplayName("Should select best strategy for market state")
    void shouldSelectBestStrategyForState() {
        StrategyPlugin trendPlugin = mock(StrategyPlugin.class);
        when(trendPlugin.getStrategyName()).thenReturn("trend-strategy");
        when(trendPlugin.getFitStateSet()).thenReturn(Set.of(ChanMarketState.UP_TREND, ChanMarketState.DOWN_TREND));
        when(trendPlugin.getStrategyScore()).thenReturn(0.8);

        StrategyPlugin rangePlugin = mock(StrategyPlugin.class);
        when(rangePlugin.getStrategyName()).thenReturn("range-strategy");
        when(rangePlugin.getFitStateSet()).thenReturn(Set.of(ChanMarketState.CONSOLIDATION));
        when(rangePlugin.getStrategyScore()).thenReturn(0.6);

        selector.registerStrategy(trendPlugin);
        selector.registerStrategy(rangePlugin);

        // Select for UP_TREND market
        selector.selectBest(ChanMarketState.UP_TREND);

        assertNotNull(selector.getActive());
        assertEquals("trend-strategy", selector.getActive().getStrategyName());
    }

    @Test
    @DisplayName("Should return null when no strategy fits market state")
    void shouldReturnNullWhenNoFit() {
        StrategyPlugin rangePlugin = mock(StrategyPlugin.class);
        when(rangePlugin.getStrategyName()).thenReturn("range-strategy");
        when(rangePlugin.getFitStateSet()).thenReturn(Set.of(ChanMarketState.CONSOLIDATION));

        selector.registerStrategy(rangePlugin);

        // UP_TREND has no fitting strategy
        selector.selectBest(ChanMarketState.UP_TREND);

        assertNull(selector.getActive());
    }

    @Test
    @DisplayName("Should select from registered strategies")
    void shouldSelectFromRegisteredStrategies() {
        StrategyPlugin lowScorePlugin = mock(StrategyPlugin.class);
        when(lowScorePlugin.getStrategyName()).thenReturn("low-score");
        when(lowScorePlugin.getFitStateSet()).thenReturn(Set.of(ChanMarketState.UP_TREND));
        when(lowScorePlugin.getStrategyScore()).thenReturn(0.5);

        selector.registerStrategy(lowScorePlugin);

        selector.selectBest(ChanMarketState.UP_TREND);

        // Should select the only registered plugin
        assertNotNull(selector.getActive());
        assertEquals("low-score", selector.getActive().getStrategyName());
        verify(lowScorePlugin).onActive(ChanMarketState.UP_TREND);
    }

    @Test
    @DisplayName("Should get score manager")
    void shouldGetScoreManager() {
        assertNotNull(selector.getScoreMgr());
    }
}