package Main;

import config.ConfigUtil;
import hft.HFTEngine;
import hft.shm.V2SHMClient;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

/**
 * HFTMain - HFT Engine Main Entry Point
 *
 * Runs the Java HFT Engine with:
 * - WebSocket market data
 * - Shared memory AI brain interface
 * - Order execution
 * - Risk management
 *
 * Usage:
 *   mvn compile exec:java -Dexec.mainClass="Main.HFTMain"
 */
public class HFTMain {
    private static HFTEngine engine;
    private static ScheduledExecutorService monitor;
    private static volatile boolean running = true;

    public static void main(String[] args) {
        // Fix Windows console encoding
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));

        try {
            // Load configuration
            String symbol = ConfigUtil.get("symbol");
            String apiKey = ConfigUtil.get("api.key");
            String secret = ConfigUtil.get("api.secret");

            System.out.println("=".repeat(60));
            System.out.println("HFT Engine Starting...");
            System.out.println("=".repeat(60));
            System.out.println("Symbol: " + symbol);
            System.out.println("API Key: " + (apiKey.isEmpty() ? "(empty - paper mode)" : "***"));
            System.out.println("Testnet: " + ConfigUtil.isTestNet());
            System.out.println("=".repeat(60));

            // Create engine config
            HFTEngine.EngineConfig config = new HFTEngine.EngineConfig();
            config.paperTrading = secret.isEmpty() || secret.startsWith("your");
            config.shmPath = System.getenv("HFT_SHM_PATH");
            if (config.shmPath == null || config.shmPath.isEmpty()) {
                config.shmPath = "D:/binance/new/data/hft_trading_shm";
            }
            config.tickSize = 0.01;  // BTCUSDT tick size

            // Initialize and start engine
            engine = new HFTEngine(symbol, config);
            engine.initialize();
            engine.start();

            // Start monitor
            monitor = Executors.newScheduledThreadPool(1);
            monitor.scheduleAtFixedRate(HFTMain::printStatus, 5, 5, TimeUnit.SECONDS);

            // Register shutdown hook
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                System.out.println("\n[MAIN] Shutdown signal received...");
                running = false;
                if (engine != null) {
                    engine.stop();
                }
            }));

            // Keep running
            while (running && !Thread.currentThread().isInterrupted()) {
                Thread.sleep(1000);
            }

        } catch (Exception e) {
            System.err.println("[MAIN] Fatal error: " + e.getMessage());
            e.printStackTrace();
        } finally {
            if (monitor != null) {
                monitor.shutdown();
            }
            System.out.println("[MAIN] Exiting");
        }
    }

    private static void printStatus() {
        if (engine == null) return;

        HFTEngine.EngineStatus status = engine.getStatus();
        System.out.printf("[%d] STATUS | ws=%b | shm_stale=%b | pos=%.4f | pnl=%.2f | degrade=%s | defense=%s%n",
            System.currentTimeMillis() / 1000,
            status.wsConnected,
            status.shmStale,
            status.position,
            status.dailyPnl,
            status.degradeLevel,
            status.defenseState
        );
    }
}
