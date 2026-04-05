"""
安全加固模块
提供安全相关的功能和检查
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import hashlib
import secrets

logger = logging.getLogger(__name__)


class SecurityHardening:
    """
    安全加固

    功能:
    - API密钥安全检查
    - 敏感信息扫描
    - 文件权限检查
    - 密码强度验证
    """

    def __init__(self):
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def run_security_check(self) -> Tuple[bool, List[str], List[str]]:
        """
        运行安全检查

        Returns:
            (passed, issues, warnings)
        """
        self.issues = []
        self.warnings = []

        # 检查环境变量
        self._check_env_variables()

        # 扫描代码中的敏感信息
        self._scan_for_secrets()

        # 检查文件权限
        self._check_file_permissions()

        # 检查日志配置
        self._check_logging_config()

        return len(self.issues) == 0, self.issues, self.warnings

    def _check_env_variables(self):
        """检查环境变量安全"""
        # 检查API密钥是否硬编码
        api_key = os.getenv('BINANCE_API_KEY', '')
        api_secret = os.getenv('BINANCE_API_SECRET', '')

        if not api_key:
            self.warnings.append("BINANCE_API_KEY not set in environment")
        elif len(api_key) < 20:
            self.issues.append("BINANCE_API_KEY seems invalid (too short)")

        if not api_secret:
            self.warnings.append("BINANCE_API_SECRET not set in environment")
        elif len(api_secret) < 20:
            self.issues.append("BINANCE_API_SECRET seems invalid (too short)")

        # 检查其他敏感配置
        if os.getenv('DEBUG', '').lower() == 'true':
            self.warnings.append("DEBUG mode is enabled")

    def _scan_for_secrets(self):
        """扫描代码中的敏感信息"""
        secret_patterns = [
            (r'api[_-]?key\s*=\s*["\'][a-zA-Z0-9]{20,}["\']', "Potential API key hardcoded"),
            (r'secret\s*=\s*["\'][a-zA-Z0-9]{20,}["\']', "Potential secret hardcoded"),
            (r'password\s*=\s*["\'][^"\']+["\']', "Potential password hardcoded"),
            (r'private[_-]?key\s*=\s*["\'][^"\']+["\']', "Potential private key hardcoded"),
        ]

        # 扫描Python文件
        for pyfile in Path('.').rglob('*.py'):
            # 跳过虚拟环境和缓存
            if 'venv' in str(pyfile) or '__pycache__' in str(pyfile):
                continue

            try:
                content = pyfile.read_text(encoding='utf-8', errors='ignore')
                for pattern, message in secret_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        self.issues.append(f"{message} in {pyfile}")
            except Exception:
                pass

    def _check_file_permissions(self):
        """检查文件权限"""
        sensitive_files = [
            '.env',
            'config/self_evolving_trader.yaml',
        ]

        for filepath in sensitive_files:
            path = Path(filepath)
            if path.exists():
                # 检查文件是否对其他用户可读写
                stat = path.stat()
                mode = stat.st_mode

                # 检查其他用户权限
                if mode & 0o007:  # 其他用户有读/写/执行权限
                    self.warnings.append(f"{filepath} has overly permissive permissions")

    def _check_logging_config(self):
        """检查日志配置安全"""
        # 检查是否可能记录敏感信息
        log_dir = Path('logs')
        if log_dir.exists():
            # 检查日志文件权限
            for logfile in log_dir.glob('*.log'):
                stat = logfile.stat()
                if stat.st_mode & 0o077:
                    self.warnings.append(f"Log file {logfile} may be accessible to other users")

    def sanitize_log_message(self, message: str) -> str:
        """
        清理日志消息中的敏感信息

        Args:
            message: 原始日志消息

        Returns:
            清理后的消息
        """
        # 替换API密钥
        message = re.sub(r'api[_-]?key[=:]\s*[a-zA-Z0-9]{20,}', 'api_key=***', message, flags=re.IGNORECASE)

        # 替换密码
        message = re.sub(r'password[=:]\s*[^\s]+', 'password=***', message, flags=re.IGNORECASE)

        # 替换密钥
        message = re.sub(r'secret[=:]\s*[a-zA-Z0-9]{20,}', 'secret=***', message, flags=re.IGNORECASE)

        return message

    def generate_secure_token(self, length: int = 32) -> str:
        """生成安全令牌"""
        return secrets.token_urlsafe(length)

    def hash_sensitive_data(self, data: str) -> str:
        """哈希敏感数据"""
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def print_security_report(self):
        """打印安全报告"""
        passed, issues, warnings = self.run_security_check()

        print("\n" + "=" * 60)
        print("Security Check Report")
        print("=" * 60)

        if passed:
            print("\n[OK] No security issues found")
        else:
            print(f"\n[FAIL] Found {len(issues)} security issues")

        if issues:
            print("\nIssues:")
            for issue in issues:
                print(f"  [FAIL] {issue}")

        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  [WARN] {warning}")

        print("=" * 60)


class SecureConfig:
    """安全配置管理"""

    @staticmethod
    def get_api_key() -> Optional[str]:
        """安全获取API密钥"""
        key = os.getenv('BINANCE_API_KEY')
        if not key:
            logger.error("BINANCE_API_KEY not found in environment")
        return key

    @staticmethod
    def get_api_secret() -> Optional[str]:
        """安全获取API密钥密码"""
        secret = os.getenv('BINANCE_API_SECRET')
        if not secret:
            logger.error("BINANCE_API_SECRET not found in environment")
        return secret

    @staticmethod
    def is_testnet() -> bool:
        """检查是否使用测试网"""
        return os.getenv('USE_TESTNET', 'true').lower() == 'true'
