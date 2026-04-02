#!/usr/bin/env python3
"""Simple test for A/B Testing framework"""

from brain_py.ab_testing import ABTest, ABTestConfig, ABTestVariant, SplitStrategyType

variants = [
    ABTestVariant(
        name='control',
        description='Control strategy',
        traffic_pct=0.5,
        version='1.0',
        is_control=True
    ),
    ABTestVariant(
        name='variant',
        description='New strategy',
        traffic_pct=0.5,
        version='2.0',
        is_control=False
    )
]

config = ABTestConfig(
    test_name='test_simple',
    description='Simple test',
    strategy=SplitStrategyType.FIXED,
    variants=variants,
    min_sample_size=10
)

ab = ABTest(config)
err = ab.start()
print('Start OK:', err is None)

# Record some results
for i in range(20):
    ab.record_result('control', 0.1 if i % 2 else -0.1, i % 2 == 1)
    ab.record_result('variant', 0.15 if i % 2 else -0.1, i % 2 == 1)

print('Results recorded')
stats = ab.calculate_statistics()
print('Statistics OK:', stats is not None)
conclusion = ab.get_conclusion()
print()
print('Conclusion:')
print(conclusion)
err = ab.stop()
print('Stop OK:', err is None)

print()
print('All tests passed!')
