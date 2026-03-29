# trading_system/ai_context.py
"""
AI 市场背景分析器。

通过 ai-compare.exe 向多个国内 AI 模型（豆包、元宝、Antafu）
异步查询市场方向，解析回答并以多数投票形成结构化结论。

调用链：
  fetch_async()          → 启动 ai-compare.exe 后台进程（非阻塞）
  wait_and_parse()       → 等待进程结束并解析最新 JSON 输出
  get_cached_context()   → 返回 4h 内的缓存结论（避免重复调用）

输出结构（market_context.json）：
  {
    "direction":   "up" | "down" | "sideways",
    "confidence":  0.0–1.0,
    "regime":      "bull" | "bear" | "neutral" | "volatile",
    "risk":        "...",
    "updated_at":  "2026-03-22T10:00:00",
    "model_votes": {"Doubao": {...}, "Yuanbao": {...}, ...}
  }
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 路径配置 ─────────────────────────────────────────────────────────────────
# 使用项目本地 tools/ai_browser/ 下的副本
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_BINARY_CWD = _PROJECT_ROOT / "tools" / "ai_browser"
_BINARY = _BINARY_CWD / "ai-browser.exe"
_QUERY_CONFIG = _BINARY_CWD / "market_query.json"
_OUTPUT_DIR = _BINARY_CWD / "output"
_CONTEXT_FILE = pathlib.Path("market_context.json")

# 缓存有效期（秒）
_CACHE_TTL = 4 * 3600

# 解析失败时的默认值
_DEFAULT_CONTEXT: dict = {
    "direction": "sideways",
    "confidence": 0.5,
    "regime": "neutral",
    "risk": "AI 分析不可用，使用默认中性立场",
    "updated_at": None,
    "model_votes": {},
}

# ── 问题模板 ─────────────────────────────────────────────────────────────────
_QUESTION_TEMPLATE = (
    "{symbol} 当前价格 {price:.0f} USDT，"
    "技术面呈{trend}趋势，"
    "过去 24h 涨跌幅 {change_pct:+.1f}%，"
    "当前 ATR 为 {atr:.1f}。"
    "请分析未来 4-24 小时的市场方向，给出结构化 JSON 判断。"
)


# ── 核心类 ───────────────────────────────────────────────────────────────────

class AIContextFetcher:
    """
    异步 AI 市场背景分析器。

    典型用法::

        fetcher = AIContextFetcher()
        fetcher.fetch_async("BTCUSDT", price=84000, trend="上涨",
                            change_pct=2.3, atr=800)
        # … 60 秒后（下一个交易周期）读取结果 …
        ctx = fetcher.get_cached_context()
        confidence_boost = ctx["confidence"] if ctx["direction"] == "up" else 0
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def fetch_async(
        self,
        symbol: str,
        price: float,
        trend: str,
        change_pct: float = 0.0,
        atr: float = 0.0,
    ) -> bool:
        """
        启动后台 ai-compare.exe 查询（非阻塞）。

        Returns:
            True 表示已成功启动进程；False 表示二进制不存在或上次查询仍在运行。
        """
        if not _BINARY.exists():
            logger.warning("ai-compare.exe 不存在：%s", _BINARY)
            return False

        if self._process is not None and self._process.poll() is None:
            logger.debug("上次 AI 查询仍在运行，跳过本次")
            return False

        question = _QUESTION_TEMPLATE.format(
            symbol=symbol, price=price, trend=trend,
            change_pct=change_pct, atr=atr,
        )
        self._patch_query_config(question)

        # 复用原始项目的登录 session（user_data 目录）
        original_user_data = pathlib.Path(r"D:\luanjian\go-persistent-browser\user_data")
        user_data_arg = str(original_user_data) if original_user_data.exists() else ""

        cmd = [str(_BINARY), "-trading", "-output", str(_OUTPUT_DIR)]
        if user_data_arg:
            cmd += ["-user-data", user_data_arg]
        self._process = subprocess.Popen(
            cmd,
            cwd=str(_BINARY_CWD),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("AI 后台查询已启动（pid=%d）question=%s", self._process.pid, question[:60])
        return True

    def is_running(self) -> bool:
        """上次查询是否仍在运行。"""
        return self._process is not None and self._process.poll() is None

    def wait_and_parse(self, timeout: int = 300) -> dict:
        """
        等待后台进程完成，解析最新输出，更新 market_context.json。

        Args:
            timeout: 最长等待秒数（默认 120s）。

        Returns:
            解析后的 market_context 字典。
        """
        if self._process is not None:
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("AI 查询超时（%ds），强制结束", timeout)
                self._process.kill()
            finally:
                self._process = None

        context = self._parse_latest_output()
        self._save_context(context)
        return context

    def get_cached_context(self) -> dict:
        """
        返回缓存的 market_context（4h 内有效），超时则返回默认值。
        """
        if not _CONTEXT_FILE.exists():
            return _DEFAULT_CONTEXT.copy()

        age = time.time() - _CONTEXT_FILE.stat().st_mtime
        if age > _CACHE_TTL:
            logger.debug("AI 缓存已过期（%.0fh），使用默认值", age / 3600)
            return _DEFAULT_CONTEXT.copy()

        try:
            return json.loads(_CONTEXT_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("读取 market_context.json 失败：%s", exc)
            return _DEFAULT_CONTEXT.copy()

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _patch_query_config(self, question: str) -> None:
        """将实际问题写入 market_query.json。"""
        try:
            cfg = json.loads(_QUERY_CONFIG.read_text(encoding="utf-8"))
            cfg["question"] = question
            _QUERY_CONFIG.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("无法更新 market_query.json：%s", exc)

    def _parse_latest_output(self) -> dict:
        """读取 output/ 目录中最新的 responses_*.json 并解析。"""
        if not _OUTPUT_DIR.exists():
            return _DEFAULT_CONTEXT.copy()

        json_files = sorted(_OUTPUT_DIR.glob("responses_*.json"), reverse=True)
        if not json_files:
            logger.warning("output/ 目录无响应文件")
            return _DEFAULT_CONTEXT.copy()

        latest = json_files[0]
        logger.info("解析 AI 输出：%s", latest.name)

        try:
            raw: dict = json.loads(latest.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("解析 JSON 失败：%s", exc)
            return _DEFAULT_CONTEXT.copy()

        return self._aggregate_votes(raw)

    def _aggregate_votes(self, raw: dict) -> dict:
        """
        从多模型回答中提取结构化判断，多数投票决定 direction。

        raw 结构（ai-compare 输出）::

            {
              "Doubao": {"content": "...", "status": "success", ...},
              "Yuanbao": {"content": "...", ...},
              ...
            }
        """
        model_votes: dict[str, dict] = {}

        for model_name, resp in raw.items():
            if resp.get("status") != "success":
                continue
            parsed = _extract_json_from_text(resp.get("content", ""))
            if parsed:
                model_votes[model_name] = parsed

        if not model_votes:
            logger.warning("所有模型解析失败，使用默认值")
            return _DEFAULT_CONTEXT.copy()

        # ── 多数投票：direction ───────────────────────────────────────────────
        direction_counts: dict[str, int] = {}
        confidence_sum = 0.0
        regime_counts: dict[str, int] = {}
        risks: list[str] = []

        for vote in model_votes.values():
            d = vote.get("direction", "sideways")
            direction_counts[d] = direction_counts.get(d, 0) + 1
            confidence_sum += float(vote.get("confidence", 0.5))
            r = vote.get("regime", "neutral")
            regime_counts[r] = regime_counts.get(r, 0) + 1
            if vote.get("risk"):
                risks.append(vote["risk"])

        n = len(model_votes)
        direction = max(direction_counts, key=direction_counts.__getitem__)
        regime = max(regime_counts, key=regime_counts.__getitem__)
        avg_confidence = confidence_sum / n

        # 如果投票不一致（无绝对多数），降低置信度
        if direction_counts[direction] < n / 2 + 0.5:
            avg_confidence *= 0.7

        context = {
            "direction": direction,
            "confidence": round(avg_confidence, 3),
            "regime": regime,
            "risk": risks[0] if risks else "无额外风险信息",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "model_votes": model_votes,
        }
        logger.info(
            "AI 多模型投票结果：direction=%s confidence=%.2f regime=%s (n=%d)",
            direction, avg_confidence, regime, n,
        )
        return context

    def _save_context(self, context: dict) -> None:
        """写入 market_context.json。"""
        try:
            _CONTEXT_FILE.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("写入 market_context.json 失败：%s", exc)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _extract_json_from_text(text: str) -> Optional[dict]:
    """
    从 AI 自由文本中提取第一个 JSON 对象。

    策略（按优先级）：
      1. 直接解析整段文本
      2. 提取 ```json ... ``` 代码块
      3. 正则匹配第一个 {...} 块
      4. 关键字解析兜底（direction/confidence/regime）
    """
    text = text.strip()

    # 策略 1：整体解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return _validate_vote(obj)
    except json.JSONDecodeError:
        pass

    # 策略 2：代码块
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block:
        try:
            obj = json.loads(code_block.group(1))
            return _validate_vote(obj)
        except json.JSONDecodeError:
            pass

    # 策略 3：第一个 {...} 块
    brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if brace_match:
        try:
            obj = json.loads(brace_match.group(0))
            return _validate_vote(obj)
        except json.JSONDecodeError:
            pass

    # 策略 4：关键字兜底解析
    return _keyword_fallback(text)


def _validate_vote(obj: dict) -> Optional[dict]:
    """校验并标准化投票字段。"""
    direction = str(obj.get("direction", "")).lower()
    if direction not in ("up", "down", "sideways"):
        # 尝试中文映射
        direction = {"涨": "up", "跌": "down", "震荡": "sideways",
                     "上涨": "up", "下跌": "down"}.get(direction, "sideways")
    try:
        confidence = float(obj.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    regime = str(obj.get("regime", "neutral")).lower()
    if regime not in ("bull", "bear", "neutral", "volatile"):
        regime = "neutral"

    return {
        "direction": direction,
        "confidence": confidence,
        "regime": regime,
        "risk": str(obj.get("risk", "")),
        "reasoning": str(obj.get("reasoning", "")),
    }


def _keyword_fallback(text: str) -> Optional[dict]:
    """通过关键词推断方向，作为最后手段。"""
    text_lower = text.lower()
    up_keywords = ["上涨", "看涨", "bullish", "uptrend", "买入", "做多", "涨势"]
    down_keywords = ["下跌", "看跌", "bearish", "downtrend", "卖出", "做空", "跌势"]

    up_score = sum(1 for kw in up_keywords if kw in text_lower)
    down_score = sum(1 for kw in down_keywords if kw in text_lower)

    if up_score == 0 and down_score == 0:
        return None

    if up_score > down_score:
        direction, confidence = "up", min(0.5 + 0.05 * up_score, 0.75)
    elif down_score > up_score:
        direction, confidence = "down", min(0.5 + 0.05 * down_score, 0.75)
    else:
        direction, confidence = "sideways", 0.45

    return {
        "direction": direction,
        "confidence": confidence,
        "regime": "neutral",
        "risk": "兜底解析，置信度较低",
        "reasoning": "(keyword fallback)",
    }


# ── 模块级单例（供 MarketAnalyzer 直接导入） ──────────────────────────────────
_fetcher = AIContextFetcher()


def fetch_async(symbol: str, price: float, trend: str,
                change_pct: float = 0.0, atr: float = 0.0) -> bool:
    """模块级便捷函数。"""
    return _fetcher.fetch_async(symbol, price, trend, change_pct, atr)


def get_cached_context() -> dict:
    """模块级便捷函数。"""
    return _fetcher.get_cached_context()


def wait_and_parse(timeout: int = 120) -> dict:
    """模块级便捷函数。"""
    return _fetcher.wait_and_parse(timeout)
