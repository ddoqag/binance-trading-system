package Main;

import config.ConfigUtil;
import hft.HFTEngine;
import hft.shm.V2SHMClient;
import ai.JavaAIBrain;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;

/**
 * HFTLauncher - HFT Engine Launcher with Java AI Brain
 *
 * Features:
 * - Pure Java AI (no Python required)
 * - Shared memory communication
 * - Paper trading mode
 * - Real-time monitoring
 *
 * Usage:
 *   mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"
 */
public class HFTLauncher {
    private static HFTEngine engine;
    private static JavaAIBrain aiBrain;
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
            System.out.println("HFT Engine V2 with Java AI Brain");
            System.out.println("=".repeat(60));
            System.out.println("Symbol: " + symbol);
            System.out.println("Paper Trading: " + ConfigUtil.isTestNet());
            System.out.println("=".repeat(60));

            // Create engine config
            HFTEngine.EngineConfig config = new HFTEngine.EngineConfig();
            config.paperTrading = true;  // Always start in paper mode
            config.shmPath = System.getenv("HFT_SHM_PATH");
            if (config.shmPath == null || config.shmPath.isEmpty()) {
                config.shmPath = "D:/binance/new/data/hft_trading_shm";
            }
            config.tickSize = 0.01;
            config.logDir = "./logs";

            // Initialize Java AI Brain
            V2SHMClient shm = new V2SHMClient(config.shmPath + "_v2");
            aiBrain = JavaAIBrain.defaults(shm);

            // Initialize engine
            engine = new HFTEngine(symbol, config);
            engine.setAIBrain(aiBrain);
            engine.initialize();

            // Start components
            engine.start();

            // Start status monitor
            monitor = Executors.newScheduledThreadPool(1);
            monitor.scheduleAtFixedRate(HFTLauncher::printStatus, 5, 5, TimeUnit.SECONDS);

            // Register shutdown hook
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                System.out.println("\n[MAIN] Shutdown...");
                running = false;
                if (engine != null) engine.stop();
            }));

            // Keep running
            while (running && !Thread.currentThread().isInterrupted()) {
                Thread.sleep(1000);
            }

        } catch (Exception e) {
            System.err.println("[MAIN] Fatal error: " + e.getMessage());
            e.printStackTrace();
        } finally {
            if (monitor != null) monitor.shutdown();
            System.out.println("[MAIN] Exited");
        }
    }

    private static void printStatus() {
        if (engine == null) return;

        HFTEngine.EngineStatus status = engine.getStatus();
        JavaAIBrain.MarketRegime regime = aiBrain.getRegime();

        System.out.printf("[%d] STATUS | ws=%b | pos=%.4f | pnl=%.2f | regime=%s (%.2f) | degrade=%s%n",
            System.currentTimeMillis() / 1000,
            status.wsConnected,
            status.position,
            status.dailyPnl,
            regime,
            aiBrain.getRegimeConfidence(),
            status.degradeLevel
        );
    }
}
