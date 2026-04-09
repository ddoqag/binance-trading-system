"""快速Phase 2测试"""
from phase2_live_test import Phase2LiveTest, LiveTestConfig

config = LiveTestConfig(
    capital=100.0,
    test_duration_hours=0.01,  # 约36秒
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=3
)

test = Phase2LiveTest(config)
result = test.run()

print()
print('='*70)
print('Phase 2 实盘测试报告')
print('='*70)
print(f'总盈亏: ${result.total_pnl:.4f} ({result.total_pnl_pct:.2%})')
print(f'成交率: {result.fill_rate:.1%}')
print(f'平均延迟: {result.avg_latency_ms:.2f}ms')
print(f'假设验证: {"通过" if result.hypothesis_validated else "未通过"}')
print(f'建议: {result.recommendation}')
print('='*70)
