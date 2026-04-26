package ws;

import chan.ChanMarketEngine;
import chan.ChanPricePoint;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import plugin.PluginHotSwapEngine;
import plugin.StrategyPlugin;
import selector.StrategySelector;
import state.ChanMarketState;
import state.TradeSignal;
import state.TradeState;
import trade.BinanceFuturesApi;
import trade.RiskManager;
import trade.TradeSignalExecutor;
import com.binance.connector.futures.client.impl.UMWebsocketClientImpl;
import com.binance.connector.futures.client.utils.WebSocketCallback;

public class WsMaRsiStrategy {
    private final String symbol;
    private final BinanceFuturesApi api;
    private final RiskManager rm;
    private final PluginHotSwapEngine hotSwap;
    private final StrategySelector selector;
    private final TradeSignalExecutor executor;
    private final ChanMarketEngine chanEng = new ChanMarketEngine();
    private final ObjectMapper mapper = new ObjectMapper();
    private long kIndex = 0;

    public WsMaRsiStrategy(String sym, BinanceFuturesApi a, RiskManager r,
                           PluginHotSwapEngine h, StrategySelector s, TradeSignalExecutor e) {
        symbol = sym;
        api = a;
        rm = r;
        hotSwap = h;
        selector = s;
        executor = e;
    }

    public void startStream() {
        UMWebsocketClientImpl ws = new UMWebsocketClientImpl();
        ws.aggTradeStream(symbol, (WebSocketCallback) msg -> {
            try {
                JsonNode root = mapper.readTree(msg);
                double price = root.get("p").asDouble();
                kIndex++;
                chanEng.feedPrice(price, System.currentTimeMillis());

                ChanMarketState state = chanEng.getCurrentState();
                ChanPricePoint point = chanEng.getPricePoint();

                selector.selectBest(state);
                StrategyPlugin active = selector.getActive();
                if (active != null) {
                    active.onTick(price, 0, 0, point);
                    TradeSignal sig = active.getTradeSignal(state, point);
                    executor.execute(sig, price);
                }

                System.out.printf("现价:%.2f 缠状态:%s 持仓:%s%n",
                        price, state.name(), TradeState.position);
            } catch (Exception e) {
                System.out.println(" 行情解析错误：" + e.getMessage());
            }
        });
    }
}
