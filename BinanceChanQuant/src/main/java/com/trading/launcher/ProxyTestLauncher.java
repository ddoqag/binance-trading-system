package com.trading.launcher;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.Socket;
import java.net.URL;
import java.net.HttpURLConnection;

/**
 * Proxy Connection Test
 * Tests proxy connectivity to Binance and other endpoints
 *
 * Note for WSL2: In WSL2, 127.0.0.1 refers to WSL2 itself.
 * To access Windows proxy, use Windows host IP (e.g., 192.168.16.1)
 */
public class ProxyTestLauncher {

    // For WSL2, use Windows host IP instead of 127.0.0.1
    private static final String PROXY_HOST = "192.168.16.1";
    private static final int PROXY_PORT = 7897;

    public static void main(String[] args) {
        System.out.println("=".repeat(60));
        System.out.println("Proxy Connection Test");
        System.out.println("=".repeat(60));
        System.out.println("Environment: WSL2");
        System.out.println("Proxy: " + PROXY_HOST + ":" + PROXY_PORT + " (Windows host)");
        System.out.println("Windows IP in WSL2: 192.168.16.1");
        System.out.println("=".repeat(60));

        // Test 1: Socket connection to proxy
        testProxySocket();

        // Test 2: HTTP connection through proxy
        testHttpConnection();

        // Test 3: Binance WebSocket URL (just URL validation)
        testBinanceUrl();

        System.out.println("=".repeat(60));
        System.out.println("Test Complete");
        System.out.println("=".repeat(60));
    }

    private static void testProxySocket() {
        System.out.println("\n[Test 1] Testing proxy socket connection...");
        System.out.println("  Note: In WSL2, use Windows IP (192.168.16.1) not 127.0.0.1");

        try {
            Proxy proxy = new Proxy(Proxy.Type.SOCKS,
                new InetSocketAddress(PROXY_HOST, PROXY_PORT));

            // Try to connect to google.com (common test endpoint)
            try (Socket socket = new Socket(proxy)) {
                socket.connect(new InetSocketAddress("www.google.com", 80), 5000);
                System.out.println("  ✓ Proxy socket connection successful");
                System.out.println("    Connected to: www.google.com:80");
            }
        } catch (Exception e) {
            System.out.println("  ✗ Proxy socket connection failed");
            System.out.println("    Error: " + e.getMessage());
            System.out.println("    Tip: Make sure your Windows proxy is running on port 7897");
        }
    }

    private static void testHttpConnection() {
        System.out.println("\n[Test 2] Testing HTTP connection through proxy...");

        try {
            // Set proxy system properties
            // For WSL2, PROXY_HOST is already set to Windows IP
            System.setProperty("http.proxyHost", PROXY_HOST);
            System.setProperty("http.proxyPort", String.valueOf(PROXY_PORT));
            System.setProperty("https.proxyHost", PROXY_HOST);
            System.setProperty("https.proxyPort", String.valueOf(PROXY_PORT));

            // Test Binance futures API
            URL url = new URL("https://fapi.binance.com/api/v3/exchangeInfo");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);

            int responseCode = conn.getResponseCode();
            System.out.println("  ✓ HTTP connection successful");
            System.out.println("    URL: https://fapi.binance.com/api/v3/exchangeInfo");
            System.out.println("    Response Code: " + responseCode);

            conn.disconnect();
        } catch (Exception e) {
            System.out.println("  ✗ HTTP connection failed");
            System.out.println("    Error: " + e.getMessage());
            System.out.println("    Tip: Check if Windows proxy is running and accessible from WSL2");
        }
    }

    private static void testBinanceUrl() {
        System.out.println("\n[Test 3] Binance WebSocket URLs...");

        String[] urls = {
            "wss://fstream.binance.com/ws/btcusdt@kline_1m",
            "wss://fstream.binance.com/ws/btcusdt@depth@100ms",
            "wss://fstream.binance.com/ws/btcusdt@aggTrade",
            "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
        };

        for (String url : urls) {
            System.out.println("  - " + url);
        }
    }
}
