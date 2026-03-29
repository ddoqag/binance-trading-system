#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础告警系统 - Alert Manager
支持多渠道告警：邮件/钉钉/等
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
import time
from dataclasses import dataclass, field
from enum import Enum
import logging
from abc import ABC, abstractmethod
from datetime import datetime


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertChannelType(Enum):
    """告警渠道类型"""
    EMAIL = "email"
    DINGTALK = "dingtalk"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"


@dataclass
class Alert:
    """告警数据类"""
    title: str
    message: str
    level: AlertLevel = AlertLevel.WARNING
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AlertResult:
    """告警发送结果"""
    channel: str
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    duration: float = 0.0


class AlertChannel(ABC):
    """告警渠道基类"""

    @abstractmethod
    def send(self, alert: Alert) -> AlertResult:
        """发送告警"""
        pass

    @property
    @abstractmethod
    def channel_type(self) -> AlertChannelType:
        """获取渠道类型"""
        pass


class EmailChannel(AlertChannel):
    """
    邮件告警渠道
    """

    def __init__(self, smtp_server: str, smtp_port: int,
                 username: str, password: str,
                 from_email: str, to_emails: List[str]):
        """
        初始化邮件告警渠道

        Args:
            smtp_server: SMTP服务器地址
            smtp_port: SMTP服务器端口
            username: SMTP用户名
            password: SMTP密码
            from_email: 发件人邮箱
            to_emails: 收件人邮箱列表
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_emails = to_emails
        self.logger = logging.getLogger('EmailChannel')

    @property
    def channel_type(self) -> AlertChannelType:
        return AlertChannelType.EMAIL

    def send(self, alert: Alert) -> AlertResult:
        """发送邮件告警"""
        start_time = time.time()

        try:
            # 创建邮件内容
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = ', '.join(self.to_emails)
            msg['Subject'] = f"[{alert.level.value.upper()}] {alert.title}"

            # 邮件正文
            body = self._format_email_body(alert)
            msg.attach(MIMEText(body, 'html'))

            # 发送邮件
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                text = msg.as_string()
                server.sendmail(self.from_email, self.to_emails, text)

            duration = time.time() - start_time
            return AlertResult(
                channel=self.channel_type.value,
                success=True,
                message=f"Email sent to {len(self.to_emails)} recipients",
                duration=duration
            )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Failed to send email alert: {e}")
            return AlertResult(
                channel=self.channel_type.value,
                success=False,
                error=str(e),
                duration=duration
            )

    def _format_email_body(self, alert: Alert) -> str:
        """格式化邮件正文"""
        tags_str = ' '.join(f"<span style='color: #666; background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 12px;'>#{tag}</span>" for tag in alert.tags)

        metadata_str = ''
        if alert.metadata:
            metadata_str = '<h4>详细信息：</h4><ul>'
            for key, value in alert.metadata.items():
                metadata_str += f"<li><strong>{key}:</strong> {value}</li>"
            metadata_str += '</ul>'

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.5;">
            <h2 style="color: {self._get_level_color(alert.level)};">{alert.title}</h2>
            <p>{alert.message}</p>
            {metadata_str}
            <p style="color: #999; font-size: 12px;">
                发送时间: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC
            </p>
            {tags_str}
        </body>
        </html>
        """

    def _get_level_color(self, level: AlertLevel) -> str:
        """根据告警级别返回颜色"""
        colors = {
            AlertLevel.INFO: "#007bff",
            AlertLevel.WARNING: "#ffc107",
            AlertLevel.ERROR: "#dc3545",
            AlertLevel.CRITICAL: "#dc3545"
        }
        return colors.get(level, "#6c757d")


class DingTalkChannel(AlertChannel):
    """
    钉钉告警渠道
    """

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        初始化钉钉告警渠道

        Args:
            webhook_url: 钉钉机器人 webhook 地址
            secret: 安全设置的签名密钥
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self.logger = logging.getLogger('DingTalkChannel')

    @property
    def channel_type(self) -> AlertChannelType:
        return AlertChannelType.DINGTALK

    def send(self, alert: Alert) -> AlertResult:
        """发送钉钉告警"""
        start_time = time.time()

        try:
            import requests
            import hashlib
            import hmac
            import base64
            from urllib.parse import quote

            url = self.webhook_url

            if self.secret:
                timestamp = str(int(time.time() * 1000))
                secret_enc = self.secret.encode('utf-8')
                string_to_sign = f"{timestamp}\n{self.secret}"
                string_to_sign_enc = string_to_sign.encode('utf-8')
                hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                sign = quote(base64.b64encode(hmac_code))
                url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

            # 构建消息体
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "title": alert.title,
                    "text": self._format_dingtalk_text(alert)
                },
                "at": {
                    "isAtAll": alert.level in [AlertLevel.ERROR, AlertLevel.CRITICAL]
                }
            }

            response = requests.post(url, json=message, timeout=10)
            response.raise_for_status()

            data = response.json()

            duration = time.time() - start_time

            if data.get('errcode') == 0:
                return AlertResult(
                    channel=self.channel_type.value,
                    success=True,
                    message="DingTalk alert sent successfully",
                    duration=duration
                )
            else:
                return AlertResult(
                    channel=self.channel_type.value,
                    success=False,
                    error=f"DingTalk API error: {data.get('errmsg')}",
                    duration=duration
                )

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Failed to send DingTalk alert: {e}")
            return AlertResult(
                channel=self.channel_type.value,
                success=False,
                error=str(e),
                duration=duration
            )

    def _format_dingtalk_text(self, alert: Alert) -> str:
        """格式化钉钉消息"""
        level_icon = {
            AlertLevel.INFO: "📢",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🔥"
        }

        tags_str = '\n'.join(f" - **{tag}**" for tag in alert.tags)

        metadata_str = ''
        if alert.metadata:
            metadata_str = '\n### 详细信息\n'
            for key, value in alert.metadata.items():
                metadata_str += f" - **{key}:** {value}\n"

        return f"""
{level_icon.get(alert.level, '📢')} **{alert.title}**

**级别:** {alert.level.value.upper()}
**时间:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC

{alert.message}

{metadata_str}

{tags_str}
        """.strip()


class AlertManager:
    """
    告警管理器 - 统一管理所有告警渠道
    """

    def __init__(self, channels: List[AlertChannel],
                 default_level: AlertLevel = AlertLevel.WARNING,
                 level_channels: Dict[AlertLevel, List[AlertChannel]] = None):
        """
        初始化告警管理器

        Args:
            channels: 所有告警渠道列表
            default_level: 默认告警级别
            level_channels: 按级别配置的渠道列表
        """
        self.channels = channels
        self.default_level = default_level
        self.level_channels = level_channels or {}
        self.logger = logging.getLogger('AlertManager')

    def send_alert(self, alert: Alert) -> List[AlertResult]:
        """
        发送告警到所有启用的渠道

        Args:
            alert: 告警对象

        Returns:
            发送结果列表
        """
        results = []

        # 确定需要发送的渠道
        channels_to_send = self._get_channels_for_alert(alert)

        self.logger.info(
            f"[{alert.level.value}] Sending alert to {len(channels_to_send)} channels: {alert.title}"
        )

        for channel in channels_to_send:
            try:
                result = channel.send(alert)
                results.append(result)
                self.logger.debug(
                    f"[{channel.channel_type.value}] Alert sent: {result.message}"
                )
            except Exception as e:
                self.logger.error(
                    f"[{channel.channel_type.value}] Failed to send alert: {e}"
                )
                results.append(AlertResult(
                    channel=channel.channel_type.value,
                    success=False,
                    error=str(e),
                    duration=0.0
                ))

        return results

    def send_risk_alert(self, check_type: str, reason: str,
                       action_taken: str, severity: str = "warning",
                       metadata: Dict[str, Any] = None):
        """
        发送风险告警

        Args:
            check_type: 检查类型
            reason: 触发原因
            action_taken: 采取的行动
            severity: 严重程度
            metadata: 详细信息
        """
        level = self._parse_level(severity)
        alert = Alert(
            title=f"风险告警: {check_type}",
            message=f"风险检查触发: {reason}\n采取行动: {action_taken}",
            level=level,
            tags=["risk", check_type],
            metadata=metadata or {}
        )
        return self.send_alert(alert)

    def send_performance_alert(self, strategy: str, metric: str,
                              current: float, threshold: float,
                              direction: str, metadata: Dict[str, Any] = None):
        """
        发送绩效告警

        Args:
            strategy: 策略名称
            metric: 指标名称
            current: 当前值
            threshold: 阈值
            direction: 方向（超过/低于）
            metadata: 详细信息
        """
        level = AlertLevel.WARNING if direction == "接近" else AlertLevel.ERROR

        alert = Alert(
            title=f"绩效告警: {strategy} {metric}",
            message=f"策略 {strategy} 的 {metric} {direction} 阈值\n当前: {current}, 阈值: {threshold}",
            level=level,
            tags=["performance", strategy, metric],
            metadata=metadata or {}
        )
        return self.send_alert(alert)

    def send_system_alert(self, component: str, error: str,
                         severity: str = "critical",
                         metadata: Dict[str, Any] = None):
        """
        发送系统告警

        Args:
            component: 组件名称
            error: 错误信息
            severity: 严重程度
            metadata: 详细信息
        """
        level = self._parse_level(severity)
        alert = Alert(
            title=f"系统告警: {component}",
            message=f"组件 {component} 发生错误: {error}",
            level=level,
            tags=["system", component],
            metadata=metadata or {}
        )
        return self.send_alert(alert)

    def _get_channels_for_alert(self, alert: Alert) -> List[AlertChannel]:
        """获取应该发送该告警的渠道"""
        # 如果有级别特定的渠道配置
        if alert.level in self.level_channels:
            return self.level_channels[alert.level]

        # 使用默认渠道
        return self.channels

    def _parse_level(self, level_str: str) -> AlertLevel:
        """解析级别字符串"""
        level_str = level_str.lower()
        if level_str == "info":
            return AlertLevel.INFO
        elif level_str == "warning":
            return AlertLevel.WARNING
        elif level_str == "error":
            return AlertLevel.ERROR
        elif level_str == "critical":
            return AlertLevel.CRITICAL
        else:
            return self.default_level


def create_alert_manager_from_config(config: Dict) -> AlertManager:
    """
    从配置创建告警管理器

    Args:
        config: 配置字典

    Returns:
        AlertManager: 告警管理器实例
    """
    channels = []

    # 邮件配置
    if config.get('email_enabled', False):
        channels.append(EmailChannel(
            smtp_server=config.get('email_smtp_server', 'smtp.163.com'),
            smtp_port=config.get('email_smtp_port', 25),
            username=config.get('email_username'),
            password=config.get('email_password'),
            from_email=config.get('email_from', config.get('email_username')),
            to_emails=config.get('email_to', []).split(',')
        ))

    # 钉钉配置
    if config.get('dingtalk_enabled', False):
        channels.append(DingTalkChannel(
            webhook_url=config.get('dingtalk_webhook'),
            secret=config.get('dingtalk_secret')
        ))

    return AlertManager(channels)
