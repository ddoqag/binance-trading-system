package com.trading.domain.trading.risk;

/**
 * RiskState - 风控状态机
 * NORMAL: 正常交易
 * CAUTION: 降频降仓（浮亏超限或仓位过高）
 * KILL: 禁止开仓（强制平仓）
 */
public enum RiskState {
    NORMAL,   // 正常交易
    CAUTION,  // 降频降仓
    KILL      // 停止交易
}
