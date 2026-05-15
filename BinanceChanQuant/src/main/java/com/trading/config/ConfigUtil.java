package com.trading.config;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

/**
 * Configuration Utility
 * Supports .env file and environment variables
 */
public class ConfigUtil {
    private static final Properties prop = new Properties();

    static {
        // Load from config.properties first (lowest priority)
        try (InputStream is = ConfigUtil.class.getClassLoader().getResourceAsStream("config.properties")) {
            if (is != null) {
                prop.load(is);
            }
        } catch (IOException e) {
            e.printStackTrace();
        }

        // Load from .env file if exists (medium priority)
        loadEnvFile();

        // Override with environment variables (highest priority)
        overrideFromEnv();
    }

    /**
     * Load .env file if present
     */
    private static void loadEnvFile() {
        try {
            // Try multiple locations for .env file
            Path[] envPaths = {
                Path.of(".env"),
                Path.of(System.getProperty("user.dir"), ".env"),
                Path.of(System.getProperty("user.dir"), "BinanceChanQuant", ".env")
            };

            for (Path envPath : envPaths) {
                if (Files.exists(envPath)) {
                    Files.lines(envPath).forEach(line -> {
                        line = line.trim();
                        if (!line.isEmpty() && !line.startsWith("#")) {
                            int idx = line.indexOf('=');
                            if (idx > 0) {
                                String key = line.substring(0, idx).trim();
                                String value = line.substring(idx + 1).trim();
                                prop.setProperty(key, value);
                            }
                        }
                    });
                    break;
                }
            }
        } catch (IOException e) {
            // Ignore
        }
    }

    /**
     * Override with environment variables
     */
    private static void overrideFromEnv() {
        // BINANCE_API_KEY / BINANCE_API_SECRET
        if (System.getenv("BINANCE_API_KEY") != null) {
            prop.setProperty("api.key", System.getenv("BINANCE_API_KEY"));
        }
        if (System.getenv("BINANCE_API_SECRET") != null) {
            prop.setProperty("api.secret", System.getenv("BINANCE_API_SECRET"));
        }
        // TESTNET / USE_TESTNET
        if (System.getenv("TESTNET") != null) {
            prop.setProperty("testnet", System.getenv("TESTNET"));
        }
        if (System.getenv("USE_TESTNET") != null) {
            prop.setProperty("testnet", System.getenv("USE_TESTNET"));
        }
        // SYMBOL
        if (System.getenv("SYMBOL") != null) {
            prop.setProperty("symbol", System.getenv("SYMBOL"));
        }
    }

    public static String get(String key) {
        return prop.getProperty(key);
    }

    public static int getInt(String key) {
        return Integer.parseInt(get(key));
    }

    public static boolean getBoolean(String key) {
        String value = get(key);
        return "true".equalsIgnoreCase(value);
    }

    public static double getDouble(String key) {
        return Double.parseDouble(get(key));
    }

    public static boolean isTestNet() {
        // Check USE_TESTNET first (from .env), then testnet (from config.properties)
        String value = get("USE_TESTNET");
        if (value == null) {
            value = get("testnet");
        }
        return "true".equalsIgnoreCase(value);
    }

    // ========== Proxy Configuration ==========

    public static String getProxyHost() {
        String host = get("PROXY_HOST");
        if (host == null) {
            host = get("proxy_host");
        }
        return host;
    }

    public static int getProxyPort() {
        String port = get("PROXY_PORT");
        if (port == null) {
            port = get("proxy_port");
        }
        return port != null ? Integer.parseInt(port) : -1;
    }

    public static String getApiKey() {
        String key = get("BINANCE_API_KEY");
        if (key == null) {
            key = get("api.key");
        }
        return key;
    }

    public static String getApiSecret() {
        String secret = get("BINANCE_API_SECRET");
        if (secret == null) {
            secret = get("api.secret");
        }
        return secret;
    }
}
