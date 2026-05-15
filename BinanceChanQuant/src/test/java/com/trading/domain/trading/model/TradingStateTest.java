package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionViability;
import com.trading.domain.trading.model.PositionHealth.HealthGrade;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Canonical TradingState Tests
 */
@DisplayName("TradingState Tests")
public class TradingStateTest {

    @Test
    @DisplayName("Empty state should have default values")
    void emptyStateDefaults() {
        TradingState state = TradingState.empty();

        assertNotNull(state.market());
        assertNotNull(state.belief());
        assertNotNull(state.position());
        assertNotNull(state.health());
        assertNotNull(state.risk());
        assertNotNull(state.execution());

        assertFalse(state.canTrade());
    }

    @Test
    @DisplayName("Initial state with price")
    void initialState() {
        TradingState state = TradingState.initial(50000);

        assertEquals(50000, state.market().currentPrice());
        assertTrue(state.version() > 0);
    }

    @Test
    @DisplayName("With methods should create new instance (immutable)")
    void withMethodsImmutable() {
        TradingState state = TradingState.initial(50000);
        long originalVersion = state.version();

        TradingState newState = state.withPosition(new TradingState.PositionSnapshot(
            0.01, 50000, 50000, 0, 0, 0.1, 5, System.currentTimeMillis(), true
        ));

        assertNotSame(state, newState);
        assertTrue(newState.version() > originalVersion);
        assertTrue(state.position().size() == 0);
    }

    @Test
    @DisplayName("Position healthy query")
    void positionHealthyQuery() {
        TradingState.HealthState healthy = new TradingState.HealthState(
            HealthGrade.HEALTHY, 0.7, 0.1, 0.7,
            PositionViability.HIGH_CONVICTION, 0, 0, true, true, 0
        );
        TradingState state1 = TradingState.initial(50000).withHealth(healthy);
        assertTrue(state1.isPositionHealthy());

        TradingState.HealthState critical = new TradingState.HealthState(
            HealthGrade.CRITICAL, 0.2, 0.6, 0.2,
            PositionViability.EXIT_PENDING, 4, 4, true, true, 0
        );
        TradingState state2 = TradingState.initial(50000).withHealth(critical);
        assertFalse(state2.isPositionHealthy());
    }

    @Test
    @DisplayName("Should exit query")
    void shouldExitQuery() {
        TradingState.HealthState watch = new TradingState.HealthState(
            HealthGrade.WATCH, 0.5, 0.2, 0.5,
            PositionViability.DECAYING, 1, 1, true, true, 0
        );
        TradingState state1 = TradingState.initial(50000).withHealth(watch);
        assertFalse(state1.shouldExit());

        TradingState.HealthState critical = new TradingState.HealthState(
            HealthGrade.CRITICAL, 0.2, 0.4, 0.3,
            PositionViability.WEAK_EDGE, 2, 3, true, true, 0
        );
        TradingState state2 = TradingState.initial(50000).withHealth(critical);
        assertTrue(state2.shouldExit());

        TradingState.HealthState highDrift = new TradingState.HealthState(
            HealthGrade.DECAYING, 0.4, 0.7, 0.3,
            PositionViability.DECAYING, 2, 2, true, true, 0
        );
        TradingState state3 = TradingState.initial(50000).withHealth(highDrift);
        assertTrue(state3.shouldExit());

        TradingState.HealthState badStructure = new TradingState.HealthState(
            HealthGrade.DECAYING, 0.4, 0.3, 0.4,
            PositionViability.WEAK_EDGE, 1, 1, true, false, 0
        );
        TradingState state4 = TradingState.initial(50000).withHealth(badStructure);
        assertTrue(state4.shouldExit());
    }

    @Test
    @DisplayName("Can trade query")
    void canTradeQuery() {
        TradingState.HealthState healthy = new TradingState.HealthState(
            HealthGrade.HEALTHY, 0.7, 0.1, 0.7,
            PositionViability.HIGH_CONVICTION, 0, 0, true, true, 0
        );
        TradingState.RiskState cleanRisk = new TradingState.RiskState(
            100, 1000, 1100, 0.0, 0.05, 5, 60, false, false, 0
        );

        TradingState state = TradingState.initial(50000)
            .withHealth(healthy)
            .withRisk(cleanRisk);

        assertTrue(state.canTrade());

        TradingState.RiskState killedRisk = new TradingState.RiskState(
            -500, 1000, 500, 0.5, 0.05, 5, 60, true, false, 0
        );
        TradingState killedState = state.withRisk(killedRisk);
        assertFalse(killedState.canTrade());
    }

    @Test
    @DisplayName("Belief state queries")
    void beliefStateQueries() {
        DirectionalBelief belief = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief entry = DirectionalBelief.of(0.65, 0.25, 0.1);

        TradingState.BeliefState beliefState = new TradingState.BeliefState(
            belief.longProb(), belief.shortProb(), belief.neutralProb(),
            belief.entropy(), belief.dominantDirection(), entry, belief, 0
        );

        TradingState state = TradingState.initial(50000).withBelief(beliefState);

        assertEquals(TradeDirection.LONG, state.dominantDirection());
        assertTrue(state.belief().longProb() > 0.6);
    }

    @Test
    @DisplayName("ToString should be readable")
    void toStringReadable() {
        TradingState state = TradingState.initial(50000);
        String str = state.toString();

        assertTrue(str.contains("TradingState"));
        assertTrue(str.contains("50000") || str.contains("v="));
    }
}