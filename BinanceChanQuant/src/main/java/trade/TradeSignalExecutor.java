package trade;

import state.TradeDirection;
import state.TradeSignal;
import state.TradeState;

public class TradeSignalExecutor {
    private final BinanceFuturesApi api;
    private final RiskManager rm;

    public TradeSignalExecutor(BinanceFuturesApi api, RiskManager rm){
        this.api=api;this.rm=rm;
    }

    public void execute(TradeSignal signal, double price) {
        double qty = rm.calcSafeQuantity(price);
        if(qty<=0) return;
        switch (signal.direction){
            case LONG:
                if("SHORT".equals(TradeState.position)) api.closeShort(TradeState.positionQty);
                api.openLong(qty);
                api.stopLossLong(qty,signal.stopLossPrice);
                TradeState.position="LONG";TradeState.positionQty=qty;
                break;
            case SHORT:
                if("LONG".equals(TradeState.position)) api.closeLong(TradeState.positionQty);
                api.openShort(qty);
                TradeState.position="SHORT";TradeState.positionQty=qty;
                break;
            case CLOSE:
                if("LONG".equals(TradeState.position)) api.closeLong(TradeState.positionQty);
                if("SHORT".equals(TradeState.position)) api.closeShort(TradeState.positionQty);
                TradeState.position="NONE";TradeState.positionQty=0;
                break;
            default:
        }
    }
}
