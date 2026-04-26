package trade;

import config.ConfigUtil;
import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;

public class BinanceFuturesApi {
    private final UMFuturesClientImpl client;
    private final String symbol;

    public BinanceFuturesApi(String apiKey, String apiSecret, String symbol) {
        this.symbol = symbol;
        this.client = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());
        setProxy();
    }

    private void setProxy() {
        try {
            String proxyHost = "192.168.16.1";
            int proxyPort = 7897;
            Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
            ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
            client.setProxy(proxyAuth);
            System.out.println(" 代理已设置：" + proxyHost + ":" + proxyPort);
        } catch (Exception e) {
            System.out.println(" 代理设置失败：" + e.getMessage());
        }
    }

    public void setLeverage(int leverage) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("leverage", leverage);
        client.account().changeInitialLeverage(params);
        System.out.println("杠杆设置为：" + leverage);
    }

    public String openLong(double qty) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("side", "BUY");
        params.put("type", "MARKET");
        params.put("quantity", qty);
        return client.account().newOrder(params);
    }

    public String openShort(double qty) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("side", "SELL");
        params.put("type", "MARKET");
        params.put("quantity", qty);
        return client.account().newOrder(params);
    }

    public String closeLong(double qty) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("side", "SELL");
        params.put("type", "MARKET");
        params.put("quantity", qty);
        params.put("reduceOnly", true);
        return client.account().newOrder(params);
    }

    public String closeShort(double qty) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("side", "BUY");
        params.put("type", "MARKET");
        params.put("quantity", qty);
        params.put("reduceOnly", true);
        return client.account().newOrder(params);
    }

    public String stopLossLong(double qty, double stop) {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);
        params.put("side", "SELL");
        params.put("type", "STOP_MARKET");
        params.put("quantity", qty);
        params.put("stopPrice", stop);
        params.put("workingType", "MARK_PRICE");
        params.put("reduceOnly", true);
        return client.account().newOrder(params);
    }

    public UMFuturesClientImpl getClient() {
        return client;
    }
}
