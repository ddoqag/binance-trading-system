cd D:\binance2\BinanceChanQuant
$ErrorActionPreference = "Continue"
Write-Host "Starting Trading System..."
& 'C:\Users\ddo\apache-maven-3.9.6\bin\mvn.cmd' compile exec:java -Dexec.mainClass="com.trading.launcher.TradingSystemLauncher" -Dexec.args="--paper" 2>&1 | Select-Object -Last 100
Write-Host "Done"