"""
部署管理器
提供系统部署和启动功能
"""

import os
import sys
import subprocess
import logging
from typing import Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime

from .health_check import HealthChecker, HealthStatus
from .config_validator import ConfigValidator
from .security_hardening import SecurityHardening

logger = logging.getLogger(__name__)


class DeploymentManager:
    """
    部署管理器

    功能:
    - 预部署检查
    - 系统启动
    - 服务管理
    - 优雅关闭
    """

    def __init__(self):
        self.health_checker = HealthChecker()
        self.config_validator = ConfigValidator()
        self.security = SecurityHardening()
        self.pre_checks: List[Callable] = []
        self.startup_tasks: List[Callable] = []
        self.shutdown_tasks: List[Callable] = []
        self._running = False

    def add_pre_check(self, check_func: Callable):
        """添加预检查"""
        self.pre_checks.append(check_func)

    def add_startup_task(self, task: Callable):
        """添加启动任务"""
        self.startup_tasks.append(task)

    def add_shutdown_task(self, task: Callable):
        """添加关闭任务"""
        self.shutdown_tasks.append(task)

    def run_pre_checks(self) -> bool:
        """
        运行所有预部署检查

        Returns:
            是否所有检查通过
        """
        print("\n" + "=" * 60)
        print("Running Pre-Deployment Checks")
        print("=" * 60)

        all_passed = True

        # 1. 环境检查
        print("\n[1/4] Checking environment...")
        env_result = self.config_validator.validate_environment()
        if not env_result.valid:
            print(f"  [FAIL] Environment check failed: {env_result.errors}")
            all_passed = False
        else:
            print("  [OK] Environment OK")

        # 2. 配置验证
        print("\n[2/4] Validating configuration...")
        config_result = self.config_validator.validate_all()
        if not config_result.valid:
            print(f"  [FAIL] Config validation failed: {config_result.errors}")
            all_passed = False
        else:
            print("  [OK] Configuration valid")

        # 3. 安全检查
        print("\n[3/4] Running security checks...")
        passed, issues, warnings = self.security.run_security_check()
        if not passed:
            print(f"  [FAIL] Security check failed: {issues}")
            all_passed = False
        else:
            print("  [OK] Security check passed")

        # 4. 自定义检查
        print("\n[4/4] Running custom checks...")
        for check in self.pre_checks:
            try:
                result = check()
                if not result:
                    all_passed = False
            except Exception as e:
                print(f"  ✗ Custom check failed: {e}")
                all_passed = False

        if all_passed:
            print("\n[OK] All pre-deployment checks passed!")
        else:
            print("\n[FAIL] Some checks failed. Please fix the issues before deploying.")

        print("=" * 60)
        return all_passed

    async def startup(self, skip_checks: bool = False) -> bool:
        """
        启动系统

        Args:
            skip_checks: 是否跳过预检查

        Returns:
            是否启动成功
        """
        print("\n" + "=" * 60)
        print("Starting Trading System")
        print("=" * 60)

        # 运行预检查
        if not skip_checks and not self.run_pre_checks():
            return False

        # 执行启动任务
        print("\nExecuting startup tasks...")
        for i, task in enumerate(self.startup_tasks, 1):
            try:
                print(f"  [{i}/{len(self.startup_tasks)}] {task.__name__}...")
                if asyncio.iscoroutinefunction(task):
                    await task()
                else:
                    task()
            except Exception as e:
                print(f"    [FAIL] Failed: {e}")
                return False

        # 启动健康检查
        await self.health_checker.start()

        self._running = True
        print("\n[OK] System started successfully!")
        print("=" * 60)

        return True

    async def shutdown(self):
        """优雅关闭系统"""
        print("\n" + "=" * 60)
        print("Shutting Down Trading System")
        print("=" * 60)

        self._running = False

        # 停止健康检查
        await self.health_checker.stop()

        # 执行关闭任务
        print("\nExecuting shutdown tasks...")
        for i, task in enumerate(self.shutdown_tasks, 1):
            try:
                print(f"  [{i}/{len(self.shutdown_tasks)}] {task.__name__}...")
                if asyncio.iscoroutinefunction(task):
                    await task()
                else:
                    task()
            except Exception as e:
                print(f"    [FAIL] Error: {e}")

        print("\n[OK] System shutdown complete")
        print("=" * 60)

    def get_status(self) -> Dict:
        """获取部署状态"""
        return {
            'running': self._running,
            'health_status': self.health_checker.get_health_report(),
            'timestamp': datetime.now().isoformat()
        }

    def create_systemd_service(self) -> str:
        """创建systemd服务文件"""
        service_content = f"""[Unit]
Description=Self-Evolving Trading System
After=network.target

[Service]
Type=simple
User={os.getenv('USER', 'trading')}
WorkingDirectory={os.getcwd()}
Environment=PYTHONPATH={os.getcwd()}
Environment=BINANCE_API_KEY=%i
Environment=BINANCE_API_SECRET=%i
ExecStart={sys.executable} run_trading_system.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
        return service_content

    def create_startup_script(self, mode: str = "paper") -> str:
        """创建启动脚本"""
        script = f"""#!/bin/bash
# Self-Evolving Trading System Startup Script
# Mode: {mode}

cd {os.getcwd()}

# Set environment variables
export PYTHONPATH={os.getcwd()}
export TRADING_MODE={mode}

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run pre-checks
echo "Running pre-deployment checks..."
python -c "
import sys
sys.path.insert(0, '.')
from production import DeploymentManager
dm = DeploymentManager()
if not dm.run_pre_checks():
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "Pre-checks failed. Aborting."
    exit 1
fi

# Start system
echo "Starting trading system..."
python run_trading_system.py --mode {mode}
"""
        return script

    def install_dependencies(self) -> bool:
        """安装依赖"""
        requirements = [
            "numpy",
            "pandas",
            "pyyaml",
            "psutil",
            "websockets",
            "requests",
        ]

        print("Installing dependencies...")
        for package in requirements:
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-q", package],
                    check=True
                )
                print(f"  ✓ {package}")
            except subprocess.CalledProcessError:
                print(f"  ✗ Failed to install {package}")
                return False

        return True


# 便捷函数
def quick_deploy_check() -> bool:
    """快速部署检查"""
    dm = DeploymentManager()
    return dm.run_pre_checks()


async def deploy_and_start(mode: str = "paper", skip_checks: bool = False) -> bool:
    """部署并启动系统"""
    dm = DeploymentManager()

    # 设置交易模式
    os.environ['TRADING_MODE'] = mode

    # 启动
    return await dm.startup(skip_checks=skip_checks)
