package com.trading.infrastructure.execution.router;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * LatencyMonitor 单元测试
 */
class LatencyMonitorTest {

    private LatencyMonitor monitor;

    @BeforeEach
    void setUp() {
        monitor = new LatencyMonitor();
    }

    @Test
    void testRecordLatency() {
        monitor.recordLatency("api1.binance.com", 50);
        monitor.recordLatency("api1.binance.com", 100);
        monitor.recordLatency("api1.binance.com", 150);

        LatencyMonitor.LatencyStats stats = monitor.getStats("api1.binance.com");
        assertNotNull(stats);
        assertEquals(3, stats.getRecentLatencies().length);
    }

    @Test
    void testP50Calculation() {
        // 记录 100 个样本：0-99
        for (int i = 0; i < 100; i++) {
            monitor.recordLatency("api1.binance.com", i);
        }

        LatencyMonitor.LatencyStats stats = monitor.getStats("api1.binance.com");
        assertTrue(stats.getP50() >= 45 && stats.getP50() <= 55);
    }

    @Test
    void testP99Calculation() {
        // 记录 100 个样本：0-99
        for (int i = 0; i < 100; i++) {
            monitor.recordLatency("api1.binance.com", i);
        }

        LatencyMonitor.LatencyStats stats = monitor.getStats("api1.binance.com");
        // P99 应该是 98-99 左右
        assertTrue(stats.getP99() >= 95);
    }

    @Test
    void testRecommendedRecvWindow() {
        // 低延迟
        for (int i = 0; i < 10; i++) {
            monitor.recordLatency("fast.api", 30);
        }
        assertEquals(5000, monitor.getRecommendedRecvWindow("fast.api"));

        // 中延迟
        for (int i = 0; i < 10; i++) {
            monitor.recordLatency("medium.api", 75);
        }
        assertEquals(10000, monitor.getRecommendedRecvWindow("medium.api"));

        // 高延迟
        for (int i = 0; i < 10; i++) {
            monitor.recordLatency("slow.api", 150);
        }
        assertEquals(20000, monitor.getRecommendedRecvWindow("slow.api"));
    }

    @Test
    void testGetBestEndpoint() {
        monitor.recordLatency("fast.api", 30);
        monitor.recordLatency("slow.api", 150);

        String best = monitor.getBestEndpoint();
        assertEquals("fast.api", best);
    }

    @Test
    void testGlobalStats() {
        monitor.recordLatency("api1", 50);
        monitor.recordLatency("api2", 100);
        monitor.recordLatency("api3", 150);

        assertTrue(monitor.getGlobalP50() > 0);
        assertTrue(monitor.getGlobalP99() > 0);
        assertTrue(monitor.getGlobalAvg() > 0);
    }

    @Test
    void testReset() {
        monitor.recordLatency("api1", 50);
        monitor.reset();

        assertEquals(0, monitor.getGlobalP50());
        assertEquals(0, monitor.getGlobalP99());
        assertNull(monitor.getStats("api1"));
    }

    @Test
    void testToString() {
        monitor.recordLatency("api1", 50);
        String str = monitor.toString();
        assertTrue(str.contains("LatencyMonitor"));
        assertTrue(str.contains("ms"));
    }
}