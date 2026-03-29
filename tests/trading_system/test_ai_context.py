# tests/trading_system/test_ai_context.py
"""
Tests for AIContextFetcher（ai-compare.exe 集成层）。

注意：测试不依赖真实的 ai-compare.exe 进程，
全部通过 mock 和临时文件验证解析逻辑。
"""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading_system.ai_context import (
    AIContextFetcher,
    _extract_json_from_text,
    _keyword_fallback,
    _validate_vote,
    get_cached_context,
)


# ── _extract_json_from_text ────────────────────────────────────────────────

def test_extract_pure_json():
    """完整 JSON 字符串直接解析。"""
    text = '{"direction":"up","confidence":0.8,"regime":"bull","risk":"低","reasoning":"趋势向好"}'
    result = _extract_json_from_text(text)
    assert result is not None
    assert result["direction"] == "up"
    assert result["confidence"] == 0.8


def test_extract_json_code_block():
    """从 markdown 代码块中提取 JSON。"""
    text = '```json\n{"direction":"down","confidence":0.65,"regime":"bear","risk":"高"}\n```'
    result = _extract_json_from_text(text)
    assert result is not None
    assert result["direction"] == "down"


def test_extract_json_embedded_in_text():
    """JSON 嵌入在文字中间。"""
    text = '根据技术分析，{"direction":"sideways","confidence":0.5,"regime":"neutral","risk":"无"} 因此建议观望。'
    result = _extract_json_from_text(text)
    assert result is not None
    assert result["direction"] == "sideways"


def test_extract_chinese_direction_mapping():
    """中文方向词自动映射。"""
    text = '{"direction":"涨","confidence":0.7,"regime":"bull","risk":"较低"}'
    result = _extract_json_from_text(text)
    assert result is not None
    assert result["direction"] == "up"


def test_extract_returns_none_for_garbage():
    """纯垃圾文本返回 None 或关键词兜底。"""
    result = _extract_json_from_text("这是一段随机文字，没有任何方向信号。")
    # 无关键词时返回 None
    assert result is None


def test_keyword_fallback_bullish():
    """关键词兜底：看涨词汇 → up。"""
    result = _keyword_fallback("市场整体看涨，上涨趋势明显，建议买入做多。")
    assert result is not None
    assert result["direction"] == "up"
    assert result["confidence"] > 0.5


def test_keyword_fallback_bearish():
    """关键词兜底：看跌词汇 → down。"""
    result = _keyword_fallback("下跌趋势持续，建议看跌做空卖出操作。")
    assert result is not None
    assert result["direction"] == "down"


# ── _validate_vote ─────────────────────────────────────────────────────────

def test_validate_clamps_confidence():
    """confidence 被截断到 [0, 1]。"""
    obj = {"direction": "up", "confidence": 1.5, "regime": "bull", "risk": ""}
    result = _validate_vote(obj)
    assert result["confidence"] == 1.0


def test_validate_unknown_regime_defaults_neutral():
    """未知 regime 回退到 neutral。"""
    obj = {"direction": "down", "confidence": 0.6, "regime": "unknown", "risk": ""}
    result = _validate_vote(obj)
    assert result["regime"] == "neutral"


# ── AIContextFetcher.aggregate_votes ───────────────────────────────────────

def _build_raw_responses(**models) -> dict:
    """辅助函数：构造 ai-compare 输出格式。"""
    result = {}
    for name, content in models.items():
        result[name] = {"status": "success", "content": content, "url": ""}
    return result


def test_aggregate_majority_up():
    """三个模型两个看涨 → direction=up。"""
    fetcher = AIContextFetcher()
    raw = _build_raw_responses(
        Doubao='{"direction":"up","confidence":0.8,"regime":"bull","risk":"低"}',
        Yuanbao='{"direction":"up","confidence":0.75,"regime":"bull","risk":"低"}',
        Antafu='{"direction":"down","confidence":0.6,"regime":"bear","risk":"高"}',
    )
    ctx = fetcher._aggregate_votes(raw)
    assert ctx["direction"] == "up"
    assert ctx["confidence"] > 0.6


def test_aggregate_all_failed_returns_default():
    """所有模型 status 非 success → 使用默认值。"""
    fetcher = AIContextFetcher()
    raw = {
        "Doubao": {"status": "error", "content": "", "url": ""},
    }
    ctx = fetcher._aggregate_votes(raw)
    assert ctx["direction"] == "sideways"
    assert ctx["confidence"] == 0.5


def test_aggregate_reduces_confidence_on_disagreement():
    """两模型各执一词 → 置信度被降低。"""
    fetcher = AIContextFetcher()
    raw = _build_raw_responses(
        Doubao='{"direction":"up","confidence":0.9,"regime":"bull","risk":"低"}',
        Yuanbao='{"direction":"down","confidence":0.9,"regime":"bear","risk":"高"}',
    )
    ctx = fetcher._aggregate_votes(raw)
    # 各占 50%，置信度应 < 原始平均值 0.9
    assert ctx["confidence"] < 0.9


# ── 缓存读写 ───────────────────────────────────────────────────────────────

def test_get_cached_context_missing_file(tmp_path, monkeypatch):
    """文件不存在时返回默认值。"""
    monkeypatch.chdir(tmp_path)
    ctx = get_cached_context()
    assert ctx["direction"] == "sideways"
    assert ctx["confidence"] == 0.5


def test_get_cached_context_expired(tmp_path, monkeypatch):
    """缓存文件超过 4h 时返回默认值。"""
    monkeypatch.chdir(tmp_path)
    ctx_file = tmp_path / "market_context.json"
    ctx_file.write_text(
        json.dumps({"direction": "up", "confidence": 0.9, "updated_at": "old"}),
        encoding="utf-8",
    )
    # 修改文件时间戳为 5h 前
    old_time = time.time() - 5 * 3600
    import os
    os.utime(ctx_file, (old_time, old_time))

    ctx = get_cached_context()
    assert ctx["direction"] == "sideways"  # 回退默认


def test_get_cached_context_valid(tmp_path, monkeypatch):
    """有效缓存直接返回。"""
    monkeypatch.chdir(tmp_path)
    data = {
        "direction": "up",
        "confidence": 0.85,
        "regime": "bull",
        "risk": "test",
        "updated_at": "2026-03-22T10:00:00+00:00",
        "model_votes": {},
    }
    (tmp_path / "market_context.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    ctx = get_cached_context()
    assert ctx["direction"] == "up"
    assert ctx["confidence"] == 0.85
