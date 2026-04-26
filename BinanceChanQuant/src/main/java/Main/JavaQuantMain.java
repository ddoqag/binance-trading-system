package Main;

import config.ConfigUtil;
import plugin.PluginHotSwapEngine;
import selector.StrategySelector;
import trade.BinanceFuturesApi;
import trade.RiskManager;
import trade.TradeSignalExecutor;
import ws.WsMaRsiStrategy;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;

public class JavaQuantMain {
    public static void main(String[] args) {
        // 解决 Windows PowerShell 控制台中文乱码
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));

        String key = ConfigUtil.get("api.key");
        String secret = ConfigUtil.get("api.secret");
        String symbol = ConfigUtil.get("symbol");
        int lev = ConfigUtil.getInt("leverage");

        BinanceFuturesApi api = new BinanceFuturesApi(key,secret,symbol);
        api.setLeverage(lev);
        RiskManager rm = new RiskManager(api.getClient());
        System.out.println(" USDT余额: " + rm.getUsdtBalance());

        StrategySelector selector = new StrategySelector();
        PluginHotSwapEngine hotSwap = new PluginHotSwapEngine(selector);
        TradeSignalExecutor exe = new TradeSignalExecutor(api,rm);

        WsMaRsiStrategy ws = new WsMaRsiStrategy(symbol,api,rm,hotSwap,selector,exe);
        ws.startStream();
    }
}
