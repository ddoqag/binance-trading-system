@echo off
chcp 65001 >nul
echo ==========================================
echo  职业级交易系统 v3.0  [模拟模式]
echo ==========================================
echo.
echo 模拟模式: 不下真实订单，但连接真实市场数据
echo.
echo 集成模块:
echo   [1] 多周期: 1h MA(12,28) + 5m MA(6,14)
echo   [2] 订单簿: 深度20档，失衡阈值1.5x
echo   [3] RL仓位: Q-table 81状态，学习最优仓位
echo.
pause

cd /d D:\binance
python live_trading_pro.py --paper

echo.
echo 模拟交易已停止
echo RL Q表: rl_qtable.json  (已保存学习结果)
pause
