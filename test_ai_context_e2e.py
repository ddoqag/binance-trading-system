#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
ai_context 端到端测试脚本。

测试内容：
  1. fetch_async() 能否正常启动 ai-compare.exe 进程
  2. wait_and_parse() 等待完成后能否解析出有效 JSON
  3. market_context.json 是否被正确写入
  4. get_cached_context() 是否读取到有效缓存
  5. MarketAnalyzer._apply_ai_context() 融合是否生效

运行方式：
  python test_ai_context_e2e.py

注意：需要 Chrome 浏览器运行（或由工具自动启动），
      且已登录豆包/元宝等国内 AI 平台。
"""
import json
import logging
import pathlib
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("e2e_test")

# 确保 D:/binance 在 sys.path
sys.path.insert(0, str(pathlib.Path(__file__).parent))


def sep(title: str):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print('─'*55)


# ─── 步骤 1：解析器单元验证（无需浏览器） ────────────────────────────────────
sep("步骤 1：解析器单元验证")

from trading_system.ai_context import _extract_json_from_text, AIContextFetcher

samples = [
    # 标准 JSON
    ('标准 JSON',
     '{"direction":"up","confidence":0.78,"regime":"bull","risk":"BTC突破关键阻力位","reasoning":"短期均线金叉"}'),
    # 代码块
    ('代码块',
     '分析结果如下：\n```json\n{"direction":"down","confidence":0.65,"regime":"bear","risk":"宏观利空"}\n```'),
    # 嵌入文字
    ('嵌入文字',
     '根据技术分析{"direction":"sideways","confidence":0.5,"regime":"neutral","risk":"震荡整理"}建议观望'),
    # 中文方向
    ('中文方向',
     '{"direction":"涨","confidence":0.7,"regime":"bull","risk":"注意回调风险"}'),
    # 关键词兜底
    ('关键词兜底',
     '目前市场整体看涨，上涨趋势明显，建议做多操作'),
]

all_ok = True
for name, text in samples:
    result = _extract_json_from_text(text)
    ok = result is not None and result.get("direction") in ("up", "down", "sideways")
    status = "✅" if ok else "❌"
    print(f"  {status} {name:12s} → {result}")
    if not ok:
        all_ok = False

print(f"\n  解析器测试：{'全部通过 ✅' if all_ok else '有失败项 ❌'}")


# ─── 步骤 2：多模型投票逻辑 ───────────────────────────────────────────────────
sep("步骤 2：多模型投票逻辑")

fetcher = AIContextFetcher()

mock_raw = {
    "Doubao": {"status": "success", "content":
               '{"direction":"up","confidence":0.82,"regime":"bull","risk":"注意阻力位","reasoning":"MACD金叉"}'},
    "Yuanbao": {"status": "success", "content":
                '```json\n{"direction":"up","confidence":0.75,"regime":"bull","risk":"宏观不确定性"}\n```'},
    "Antafu": {"status": "success", "content":
               '目前市场呈上涨趋势，看涨情绪明显，建议做多，注意止损。'},
}

ctx = fetcher._aggregate_votes(mock_raw)
print(f"  方向: {ctx['direction']}")
print(f"  置信度: {ctx['confidence']:.3f}")
print(f"  市场状态: {ctx['regime']}")
print(f"  风险: {ctx['risk']}")
print(f"  参与模型数: {len(ctx['model_votes'])}")

vote_ok = ctx["direction"] == "up" and ctx["confidence"] > 0.6
print(f"\n  投票测试：{'通过 ✅' if vote_ok else '失败 ❌'}")


# ─── 步骤 3：fetch_async 启动测试（实际调用 ai-compare.exe） ─────────────────
sep("步骤 3：fetch_async 启动 ai-compare.exe")

import numpy as np
import pandas as pd

# 模拟当前 BTC 市价数据
n = 60
close = np.linspace(82000, 84500, n)
df = pd.DataFrame({
    "open": close - 100, "high": close + 200,
    "low": close - 200, "close": close,
    "volume": np.ones(n) * 500,
})
price = float(close[-1])
change_pct = (close[-1] - close[0]) / close[0] * 100
atr = float(np.diff(close).std() * 14)

print(f"  模拟行情: BTC @ {price:.0f} USDT  涨跌幅={change_pct:+.1f}%  ATR={atr:.0f}")
print(f"  正在启动 ai-compare.exe（-in 仅国内模型）...")

from trading_system.ai_context import fetch_async, wait_and_parse, get_cached_context, _fetcher

started = fetch_async(
    symbol="BTCUSDT",
    price=price,
    trend="上涨",
    change_pct=change_pct,
    atr=atr,
)

if not started:
    print("  ⚠️  进程未启动（可能 exe 不存在或上次仍在运行）")
else:
    print(f"  ✅ 进程已启动（pid={_fetcher._process.pid if _fetcher._process else 'N/A'}），后台运行中...")
    print(f"  ℹ️  生产模式：不等待，下一个交易周期再读缓存")
    print(f"  ℹ️  若需手动等待：python -c \"from trading_system.ai_context import wait_and_parse; print(wait_and_parse(300))\"")

    # 等待最多 5 分钟（首次启动浏览器较慢）
    import subprocess
    choice = input("\n  是否等待完整响应？[y/N] ").strip().lower()
    if choice == "y":
        print("  等待中（最长 300 秒）...")
        ctx = wait_and_parse(timeout=300)
        print(f"\n  解析结果:")
        print(f"    方向:   {ctx['direction']}")
        print(f"    置信度: {ctx['confidence']:.3f}")
        print(f"    状态:   {ctx['regime']}")
        print(f"    风险:   {ctx['risk']}")
        print(f"    更新时间: {ctx.get('updated_at', 'N/A')}")
        print(f"    模型数: {len(ctx.get('model_votes', {}))}")
        cf = pathlib.Path("market_context.json")
        file_ok = cf.exists() and len(cf.read_text(encoding="utf-8", errors="replace")) > 10
        print(f"\n  market_context.json 写入：{'✅' if file_ok else '❌'}")
    else:
        print("  跳过等待，继续下一步...")


# ─── 步骤 4：缓存读取 ────────────────────────────────────────────────────────
sep("步骤 4：缓存读取 get_cached_context()")

cached = get_cached_context()
print(f"  direction  = {cached['direction']}")
print(f"  confidence = {cached['confidence']}")
print(f"  updated_at = {cached.get('updated_at', '(无缓存，使用默认值)')}")


# ─── 步骤 5：MarketAnalyzer 融合 ─────────────────────────────────────────────
sep("步骤 5：MarketAnalyzer._apply_ai_context() 融合")

from ai_trading.market_analyzer import MarketAnalyzer, TrendType, MarketRegime

analyzer = MarketAnalyzer()
fake_result = {
    "trend": TrendType.UPTREND,
    "regime": MarketRegime.BULL,
    "confidence": 0.70,
    "current_price": price,
}
fused = analyzer._apply_ai_context(fake_result, df)

print(f"  融合前 confidence: 0.700")
print(f"  融合后 confidence: {fused['confidence']:.3f}")
print(f"  ai_context 字段:   {fused.get('ai_context', '(无缓存，未注入)')}")

print(f"\n{'─'*55}")
print("  端到端测试完成 ✅")
print('─'*55)
