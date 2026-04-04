# -*- coding: utf-8 -*-
"""
alert_notifier.py - 实时异常告警通知系统

支持多种通知渠道：
- 钉钉 (DingTalk)
- 飞书 (Lark/Feishu)
- Telegram
- 企业微信 (WeCom)
- 本地日志（兜底）

Usage:
    from core.alert_notifier import AlertNotifier, AlertLevel
    
    notifier = AlertNotifier(
        dingtalk_webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx",
        telegram_bot_token="xxx",
        telegram_chat_id="xxx"
    )
    
    await notifier.send_alert(
        level=AlertLevel.CRITICAL,
        title="模型更新失败",
        message="Regime Detector HMM 训练失败，已降级到 fallback 模式",
        metadata={"latency_ms": 5.2, "tick_count": 12345}
    )
"""

import asyncio
import json
import logging
import aiohttp
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"           # 信息通知
    WARNING = "warning"     # 警告
    ERROR = "error"         # 错误
    CRITICAL = "critical"   # 紧急（需要立即处理）


class AlertNotifier:
    """
    多通道告警通知器
    
    支持同时配置多个通知渠道，失败时自动降级到下一个渠道
    """
    
    def __init__(
        self,
        # 钉钉
        dingtalk_webhook: Optional[str] = None,
        dingtalk_secret: Optional[str] = None,
        # 飞书
        lark_webhook: Optional[str] = None,
        # Telegram
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        # 企业微信
        wecom_webhook: Optional[str] = None,
        # 全局配置
        min_level: AlertLevel = AlertLevel.WARNING,
        rate_limit_seconds: float = 5.0,  # 同类型告警限流
        timeout: float = 3.0
    ):
        """
        初始化告警通知器
        
        Args:
            dingtalk_webhook: 钉钉机器人 webhook URL
            dingtalk_secret: 钉钉机器人安全密钥（可选）
            lark_webhook: 飞书机器人 webhook URL
            telegram_bot_token: Telegram Bot Token
            telegram_chat_id: Telegram Chat ID
            wecom_webhook: 企业微信 webhook URL
            min_level: 最小告警级别（低于此级别不发送）
            rate_limit_seconds: 同类型告警限流间隔
            timeout: HTTP 请求超时
        """
        # 配置
        self.dingtalk_webhook = dingtalk_webhook
        self.dingtalk_secret = dingtalk_secret
        self.lark_webhook = lark_webhook
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.wecom_webhook = wecom_webhook
        
        self.min_level = min_level
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout = timeout
        
        # 状态
        self._last_alert_time: Dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def send_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        force: bool = False
    ) -> bool:
        """
        发送告警通知
        
        Args:
            level: 告警级别
            title: 标题
            message: 详细内容
            metadata: 附加元数据（如延迟、tick_count 等）
            force: 是否强制发送（忽略限流）
        
        Returns:
            是否成功发送
        """
        # 级别过滤
        if not self._should_send(level):
            return False
        
        # 限流检查
        alert_key = f"{level.value}:{title}"
        if not force and not self._check_rate_limit(alert_key):
            logger.debug(f"Alert rate limited: {alert_key}")
            return False
        
        # 构建通知内容
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = self._format_message(level, title, message, metadata, timestamp)
        
        # 发送到所有配置的渠道（并行）
        tasks = []
        
        if self.dingtalk_webhook:
            tasks.append(self._send_dingtalk(level, title, full_message))
        if self.lark_webhook:
            tasks.append(self._send_lark(level, title, full_message))
        if self.telegram_bot_token and self.telegram_chat_id:
            tasks.append(self._send_telegram(level, title, full_message))
        if self.wecom_webhook:
            tasks.append(self._send_wecom(level, title, full_message))
        
        # 如果没有配置任何渠道，只记录日志
        if not tasks:
            logger.warning(f"[ALERT] {level.value.upper()}: {title} - {message}")
            return True
        
        # 并行发送，只要有一个成功就算成功
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = any(r is True for r in results)
        
        if success:
            self._last_alert_time[alert_key] = asyncio.get_event_loop().time()
        else:
            # 所有渠道都失败，记录到本地日志
            logger.error(f"[ALERT FAILED] {level.value.upper()}: {title} - {message}")
        
        return success
    
    def _should_send(self, level: AlertLevel) -> bool:
        """检查是否应该发送该级别的告警"""
        level_priority = {
            AlertLevel.INFO: 0,
            AlertLevel.WARNING: 1,
            AlertLevel.ERROR: 2,
            AlertLevel.CRITICAL: 3
        }
        return level_priority[level] >= level_priority[self.min_level]
    
    def _check_rate_limit(self, alert_key: str) -> bool:
        """检查是否可以通过限流"""
        now = asyncio.get_event_loop().time()
        last_time = self._last_alert_time.get(alert_key, 0)
        return (now - last_time) >= self.rate_limit_seconds
    
    def _format_message(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]],
        timestamp: str
    ) -> str:
        """格式化通知内容"""
        lines = [
            f"[{level.value.upper()}] {title}",
            f"时间: {timestamp}",
            f"详情: {message}"
        ]
        
        if metadata:
            lines.append("元数据:")
            for key, value in metadata.items():
                lines.append(f"  {key}: {value}")
        
        return "\n".join(lines)
    
    # ========================================================================
    # 各平台发送实现
    # ========================================================================
    
    async def _send_dingtalk(self, level: AlertLevel, title: str, message: str) -> bool:
        """发送到钉钉"""
        try:
            import hmac
            import hashlib
            import base64
            import urllib.parse
            
            # 计算签名
            timestamp = str(round(asyncio.get_event_loop().time() * 1000))
            if self.dingtalk_secret:
                string_to_sign = f"{timestamp}\n{self.dingtalk_secret}"
                sign = base64.b64encode(
                    hmac.new(
                        self.dingtalk_secret.encode('utf-8'),
                        string_to_sign.encode('utf-8'),
                        digestmod=hashlib.sha256
                    ).digest()
                ).decode('utf-8')
                sign = urllib.parse.quote(sign)
                webhook = f"{self.dingtalk_webhook}&timestamp={timestamp}&sign={sign}"
            else:
                webhook = self.dingtalk_webhook
            
            # 颜色根据级别
            color_map = {
                AlertLevel.INFO: "#3399FF",
                AlertLevel.WARNING: "#FF9900",
                AlertLevel.ERROR: "#FF3333",
                AlertLevel.CRITICAL: "#990000"
            }
            
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[P10 Trading] {title}",
                    "text": f"<font color='{color_map[level]}'>**[{level.value.upper()}]** {title}</font>\n\n{message}"
                }
            }
            
            session = await self._get_session()
            async with session.post(webhook, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("errcode") == 0:
                        return True
                    else:
                        logger.error(f"DingTalk API error: {result}")
                else:
                    logger.error(f"DingTalk HTTP error: {resp.status}")
        except Exception as e:
            logger.error(f"DingTalk send failed: {e}")
        
        return False
    
    async def _send_lark(self, level: AlertLevel, title: str, message: str) -> bool:
        """发送到飞书"""
        try:
            color_map = {
                AlertLevel.INFO: "blue",
                AlertLevel.WARNING: "orange",
                AlertLevel.ERROR: "red",
                AlertLevel.CRITICAL: "red"
            }
            
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": f"[P10 Trading] {title}"
                        },
                        "template": color_map[level]
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": message.replace("\n", "\n\n")
                            }
                        }
                    ]
                }
            }
            
            session = await self._get_session()
            async with session.post(self.lark_webhook, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("code") == 0:
                        return True
                    else:
                        logger.error(f"Lark API error: {result}")
                else:
                    logger.error(f"Lark HTTP error: {resp.status}")
        except Exception as e:
            logger.error(f"Lark send failed: {e}")
        
        return False
    
    async def _send_telegram(self, level: AlertLevel, title: str, message: str) -> bool:
        """发送到 Telegram"""
        try:
            emoji_map = {
                AlertLevel.INFO: "ℹ️",
                AlertLevel.WARNING: "⚠️",
                AlertLevel.ERROR: "❌",
                AlertLevel.CRITICAL: "🚨"
            }
            
            text = f"{emoji_map[level]} *[{level.value.upper()}] {title}*\n\n{message}"
            
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_notification": level == AlertLevel.INFO
            }
            
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("ok"):
                        return True
                    else:
                        logger.error(f"Telegram API error: {result}")
                else:
                    logger.error(f"Telegram HTTP error: {resp.status}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
        
        return False
    
    async def _send_wecom(self, level: AlertLevel, title: str, message: str) -> bool:
        """发送到企业微信"""
        try:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"[P10 Trading] [{level.value.upper()}] {title}\n\n{message}"
                }
            }
            
            session = await self._get_session()
            async with session.post(self.wecom_webhook, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("errcode") == 0:
                        return True
                    else:
                        logger.error(f"WeCom API error: {result}")
                else:
                    logger.error(f"WeCom HTTP error: {resp.status}")
        except Exception as e:
            logger.error(f"WeCom send failed: {e}")
        
        return False
    
    async def close(self):
        """关闭 HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()


# ========================================================================
# 快捷函数
# ========================================================================

async def send_critical_alert(
    title: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
    **notifier_kwargs
):
    """发送紧急告警的快捷函数"""
    notifier = AlertNotifier(**notifier_kwargs)
    return await notifier.send_alert(
        level=AlertLevel.CRITICAL,
        title=title,
        message=message,
        metadata=metadata
    )


# 示例配置（复制到 config 中使用）
EXAMPLE_CONFIG = {
    # 钉钉
    "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "dingtalk_secret": "xxx",
    
    # 飞书
    "lark_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
    
    # Telegram
    "telegram_bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "telegram_chat_id": "-1001234567890",
    
    # 企业微信
    "wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
    
    # 全局配置
    "min_level": "warning",
    "rate_limit_seconds": 5.0
}
