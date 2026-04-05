"""
配置验证器
验证系统配置的正确性和完整性
"""

import os
import yaml
import logging
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: List[str]
    warnings: List[str]


class ConfigValidator:
    """
    配置验证器

    验证项目:
    - 必需字段存在
    - 数据类型正确
    - 数值范围合理
    - API密钥格式
    - 文件路径存在
    """

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self, config_path: str = "config/self_evolving_trader.yaml") -> ValidationResult:
        """验证所有配置"""
        self.errors = []
        self.warnings = []

        # 加载配置
        config = self._load_config(config_path)
        if config is None:
            return ValidationResult(False, ["Failed to load config"], [])

        # 验证各个部分
        self._validate_trading_mode(config)
        self._validate_risk_limits(config)
        self._validate_strategies(config)
        self._validate_api_keys(config)
        self._validate_paths(config)

        return ValidationResult(
            valid=len(self.errors) == 0,
            errors=self.errors,
            warnings=self.warnings
        )

    def _load_config(self, path: str) -> Optional[Dict]:
        """加载配置文件"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.errors.append(f"Config load error: {e}")
            return None

    def _validate_trading_mode(self, config: Dict):
        """验证交易模式"""
        mode = config.get('trading_mode')
        valid_modes = ['backtest', 'paper', 'live']

        if not mode:
            self.errors.append("Missing trading_mode")
        elif mode not in valid_modes:
            self.errors.append(f"Invalid trading_mode: {mode}. Must be one of {valid_modes}")

        # 实盘模式额外检查
        if mode == 'live':
            self.warnings.append("Trading mode is LIVE - ensure all safety checks are enabled")

            # 检查Kill Switch
            if not config.get('risk_limits', {}).get('kill_switch_enabled', True):
                self.errors.append("Kill switch must be enabled for live trading")

    def _validate_risk_limits(self, config: Dict):
        """验证风险限制"""
        risk = config.get('risk_limits', {})

        # 必需字段
        required = [
            'max_single_position_pct',
            'max_total_position_pct',
            'max_daily_loss_pct',
            'max_drawdown_pct'
        ]

        for field in required:
            if field not in risk:
                self.errors.append(f"Missing risk limit: {field}")
                continue

            value = risk[field]
            if not isinstance(value, (int, float)):
                self.errors.append(f"{field} must be a number")
                continue

            if not 0 < value <= 1:
                self.errors.append(f"{field} must be between 0 and 1")

        # 检查逻辑一致性
        if 'max_single_position_pct' in risk and 'max_total_position_pct' in risk:
            if risk['max_single_position_pct'] > risk['max_total_position_pct']:
                self.errors.append("max_single_position_pct cannot exceed max_total_position_pct")

        # 警告过于宽松的风险设置
        if risk.get('max_daily_loss_pct', 0) > 0.1:
            self.warnings.append("max_daily_loss_pct is very high (>10%)")

        if risk.get('max_drawdown_pct', 0) > 0.3:
            self.warnings.append("max_drawdown_pct is very high (>30%)")

    def _validate_strategies(self, config: Dict):
        """验证策略配置"""
        strategies = config.get('strategies', [])

        if not strategies:
            self.errors.append("No strategies configured")
            return

        total_weight = 0
        enabled_count = 0

        for i, strategy in enumerate(strategies):
            prefix = f"Strategy[{i}]"

            # 检查必需字段
            if 'name' not in strategy:
                self.errors.append(f"{prefix}: Missing name")
                continue

            name = strategy['name']

            if 'weight' not in strategy:
                self.errors.append(f"{prefix} ({name}): Missing weight")
            else:
                weight = strategy['weight']
                if not 0 <= weight <= 1:
                    self.errors.append(f"{prefix} ({name}): weight must be between 0 and 1")
                else:
                    if strategy.get('enabled', False):
                        total_weight += weight
                        enabled_count += 1

            # 检查参数
            if 'params' in strategy:
                params = strategy['params']
                if not isinstance(params, dict):
                    self.errors.append(f"{prefix} ({name}): params must be a dictionary")

        # 检查权重总和
        if enabled_count > 0 and abs(total_weight - 1.0) > 0.01:
            self.warnings.append(f"Strategy weights sum to {total_weight:.2f}, recommended: 1.0")

    def _validate_api_keys(self, config: Dict):
        """验证API密钥"""
        # 检查环境变量
        api_key = os.getenv('BINANCE_API_KEY') or config.get('api_key', '')
        api_secret = os.getenv('BINANCE_API_SECRET') or config.get('api_secret', '')

        # 移除模板占位符检查
        if api_key and not api_key.startswith('${'):
            if len(api_key) < 10:
                self.warnings.append("API key seems too short")

        if api_secret and not api_secret.startswith('${'):
            if len(api_secret) < 10:
                self.warnings.append("API secret seems too short")

        # 实盘模式必须有API密钥
        if config.get('trading_mode') == 'live':
            if not api_key or api_key.startswith('${'):
                self.errors.append("Live trading requires BINANCE_API_KEY")
            if not api_secret or api_secret.startswith('${'):
                self.errors.append("Live trading requires BINANCE_API_SECRET")

    def _validate_paths(self, config: Dict):
        """验证文件路径"""
        paths_to_check = [
            ('logging', 'file'),
        ]

        for section, key in paths_to_check:
            path = config.get(section, {}).get(key)
            if path:
                parent = Path(path).parent
                if not parent.exists():
                    self.warnings.append(f"Directory does not exist: {parent}")

    def validate_environment(self) -> ValidationResult:
        """验证环境"""
        self.errors = []
        self.warnings = []

        # 检查Python版本
        import sys
        if sys.version_info < (3, 8):
            self.errors.append("Python 3.8+ required")

        # 检查必需包
        required_packages = [
            'numpy',
            'pandas',
            'yaml'
        ]

        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                self.errors.append(f"Required package not installed: {package}")

        # 检查可选包
        optional_packages = [
            ('psutil', 'system monitoring'),
            ('websockets', 'real-time updates'),
        ]

        for package, purpose in optional_packages:
            try:
                __import__(package)
            except ImportError:
                self.warnings.append(f"Optional package {package} not installed ({purpose})")

        return ValidationResult(
            valid=len(self.errors) == 0,
            errors=self.errors,
            warnings=self.warnings
        )

    def print_report(self, result: ValidationResult):
        """打印验证报告"""
        print("\n" + "=" * 60)
        print("Configuration Validation Report")
        print("=" * 60)

        if result.valid:
            print("\n[OK] Configuration is valid")
        else:
            print("\n[FAIL] Configuration has errors")

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for error in result.errors:
                print(f"  [FAIL] {error}")

        if result.warnings:
            print(f"\nWarnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  [WARN] {warning}")

        print("=" * 60)
