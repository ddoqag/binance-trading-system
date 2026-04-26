@echo off
REM HFT Engine Build & Run Script
REM Requires Maven to be installed

cd /d %~dp0

echo Building HFT Engine...
call mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"

pause
