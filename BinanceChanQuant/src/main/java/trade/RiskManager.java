package trade;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import state.TradeState;
import java.util.LinkedHashMap;

public class RiskManager {
    private final UMFuturesClientImpl futuresClient;
    private final ObjectMapper mapper = new ObjectMapper();

    public RiskManager(UMFuturesClientImpl futuresClient) {
        this.futuresClient = futuresClient;
    }

    public double getUsdtBalance() {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            String json = futuresClient.account().futuresAccountBalance(params);
            JsonNode root = mapper.readTree(json);
            for(JsonNode n : root) {
                if("USDT".equals(n.get("asset").asText())) {
                    return n.get("balance").asDouble();
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return 0;
    }

    public double calcSafeQuantity(double price) {
        double bal = getUsdtBalance();
        double use = bal * TradeState.MAX_POS_RATIO;
        double qty = use / price;
        return Math.floor(qty * 1000) / 1000.0;
    }
}
