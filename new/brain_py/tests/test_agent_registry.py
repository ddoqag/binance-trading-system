"""
test_agent_registry.py - 策略注册表单元测试

测试覆盖:
- 策略注册/注销
- 策略获取和列表
- 热更新功能
- 模块动态加载
- 错误处理
"""

import os
import sys
import time
import tempfile
import threading
from unittest import TestCase, main

import pytest

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_registry import (
    AgentRegistry, BaseAgent, AgentMetadata,
    AgentStatus, StrategyPriority, get_global_registry
)


class MockAgent(BaseAgent):
    """测试用策略类"""

    METADATA = {
        'version': '1.0.0',
        'description': 'Test agent',
        'author': 'test',
        'priority': StrategyPriority.NORMAL.value,
        'tags': ['test', 'mock']
    }

    def __init__(self, config=None):
        super().__init__(config)
        self.initialized = False
        self.shutdown_called = False
        self.predict_count = 0

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def predict(self, state):
        self.predict_count += 1
        return {'action': 'buy', 'confidence': 0.8}

    def shutdown(self) -> None:
        self.shutdown_called = True


class FailingAgent(BaseAgent):
    """初始化失败的策略"""

    def initialize(self) -> bool:
        return False

    def predict(self, state):
        return None

    def shutdown(self) -> None:
        pass


class ErrorAgent(BaseAgent):
    """抛出异常的策略"""

    def initialize(self) -> bool:
        raise RuntimeError("Init error")

    def predict(self, state):
        return None

    def shutdown(self) -> None:
        pass


class TestAgentRegistry(TestCase):
    """测试策略注册表"""

    def setUp(self):
        """每个测试前执行"""
        self.registry = AgentRegistry()

    def tearDown(self):
        """每个测试后执行"""
        self.registry.clear()

    def test_register_success(self):
        """测试成功注册策略"""
        agent = MockAgent()
        metadata = AgentMetadata(name='test_agent', version='1.0.0')

        result = self.registry.register('test_agent', agent, metadata)

        self.assertTrue(result)
        self.assertTrue(agent.initialized)
        self.assertEqual(len(self.registry.list_agents()), 1)

    def test_register_duplicate(self):
        """测试重复注册"""
        agent1 = MockAgent()
        agent2 = MockAgent()

        self.registry.register('agent', agent1)
        result = self.registry.register('agent', agent2)

        self.assertFalse(result)

    def test_register_failing_init(self):
        """测试初始化失败的策略"""
        agent = FailingAgent()

        result = self.registry.register('failing', agent)

        self.assertFalse(result)
        self.assertEqual(len(self.registry.list_agents()), 0)

    def test_register_error_init(self):
        """测试初始化异常的策略"""
        agent = ErrorAgent()

        result = self.registry.register('error', agent)

        self.assertFalse(result)

    def test_unregister_success(self):
        """测试成功注销"""
        agent = MockAgent()
        self.registry.register('agent', agent)

        result = self.registry.unregister('agent')

        self.assertTrue(result)
        self.assertTrue(agent.shutdown_called)
        self.assertEqual(len(self.registry.list_agents()), 0)

    def test_unregister_not_found(self):
        """测试注销不存在的策略"""
        result = self.registry.unregister('nonexistent')

        self.assertFalse(result)

    def test_get_agent(self):
        """测试获取策略"""
        agent = MockAgent()
        self.registry.register('agent', agent)

        retrieved = self.registry.get('agent')

        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved, agent)

    def test_get_not_found(self):
        """测试获取不存在的策略"""
        result = self.registry.get('nonexistent')

        self.assertIsNone(result)

    def test_list_agents(self):
        """测试列出策略"""
        agent1 = MockAgent()
        agent2 = MockAgent()

        self.registry.register('agent1', agent1)
        self.registry.register('agent2', agent2)

        agents = self.registry.list_agents()

        self.assertEqual(len(agents), 2)
        names = [a.name for a in agents]
        self.assertIn('agent1', names)
        self.assertIn('agent2', names)

    def test_list_by_status(self):
        """测试按状态过滤"""
        agent = MockAgent()
        self.registry.register('agent', agent)
        self.registry.pause('agent')

        active = self.registry.list_agents(AgentStatus.ACTIVE)
        paused = self.registry.list_agents(AgentStatus.PAUSED)

        self.assertEqual(len(active), 0)
        self.assertEqual(len(paused), 1)

    def test_pause_resume(self):
        """测试暂停和恢复"""
        agent = MockAgent()
        self.registry.register('agent', agent)

        # 暂停
        pause_result = self.registry.pause('agent')
        self.assertTrue(pause_result)

        # 获取暂停的策略应返回None
        retrieved = self.registry.get('agent')
        self.assertIsNone(retrieved)

        # 恢复
        resume_result = self.registry.resume('agent')
        self.assertTrue(resume_result)

        # 恢复后应能获取
        retrieved = self.registry.get('agent')
        self.assertIsNotNone(retrieved)

    def test_get_info(self):
        """测试获取策略信息"""
        agent = MockAgent()
        metadata = AgentMetadata(name='agent', version='2.0.0')
        self.registry.register('agent', agent, metadata)

        info = self.registry.get_info('agent')

        self.assertIsNotNone(info)
        self.assertEqual(info.name, 'agent')
        self.assertEqual(info.metadata.version, '2.0.0')
        self.assertEqual(info.status, AgentStatus.ACTIVE)

    def test_get_stats(self):
        """测试获取统计信息"""
        agent = MockAgent()
        self.registry.register('agent', agent)

        # 模拟调用
        self.registry.get('agent')
        self.registry.get('agent')

        stats = self.registry.get_stats()

        self.assertEqual(stats['total_agents'], 1)
        self.assertEqual(stats['active'], 1)
        self.assertEqual(stats['total_calls'], 2)

    def test_hooks(self):
        """测试事件钩子"""
        events = []

        def on_register(name, info):
            events.append(('register', name))

        def on_unregister(name, info):
            events.append(('unregister', name))

        self.registry.add_hook('on_register', on_register)
        self.registry.add_hook('on_unregister', on_unregister)

        agent = MockAgent()
        self.registry.register('agent', agent)
        self.registry.unregister('agent')

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0], ('register', 'agent'))
        self.assertEqual(events[1], ('unregister', 'agent'))

    def test_clear(self):
        """测试清空所有策略"""
        agent1 = MockAgent()
        agent2 = MockAgent()

        self.registry.register('agent1', agent1)
        self.registry.register('agent2', agent2)

        self.registry.clear()

        self.assertEqual(len(self.registry.list_agents()), 0)
        self.assertTrue(agent1.shutdown_called)
        self.assertTrue(agent2.shutdown_called)


class TestHotReload(TestCase):
    """测试热更新功能"""

    def setUp(self):
        self.registry = AgentRegistry()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        self.registry.clear()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hot_reload_success(self):
        """测试成功热更新 - Windows兼容版本"""
        import sys
        import os

        # 创建临时目录结构，模拟 brain_py 目录
        temp_brain_py = os.path.join(self.temp_dir, 'brain_py_temp')
        os.makedirs(temp_brain_py, exist_ok=True)

        # 复制 agent_registry 到临时目录
        import shutil
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        registry_source = os.path.join(current_dir, 'agent_registry.py')
        registry_dest = os.path.join(temp_brain_py, 'agent_registry.py')
        shutil.copy2(registry_source, registry_dest)

        # 创建初始策略文件
        module_path = os.path.join(temp_brain_py, 'reloadable_agent.py')
        with open(module_path, 'w') as f:
            f.write('''
from agent_registry import BaseAgent

class ReloadableAgent(BaseAgent):
    VERSION = 1

    def initialize(self):
        return True

    def predict(self, state):
        return {'version': 1}

    def shutdown(self):
        pass
''')

        # 临时添加目录到路径
        if temp_brain_py not in sys.path:
            sys.path.insert(0, temp_brain_py)

        try:
            # 加载
            success = self.registry.load_from_module(module_path, 'ReloadableAgent', 'reloadable')
            self.assertTrue(success)

            agent1 = self.registry.get('reloadable')
            self.assertEqual(agent1.VERSION, 1)

            # 修改文件
            time.sleep(0.1)  # 确保mtime变化
            with open(module_path, 'w') as f:
                f.write('''
from agent_registry import BaseAgent

class ReloadableAgent(BaseAgent):
    VERSION = 2

    def initialize(self):
        return True

    def predict(self, state):
        return {'version': 2}

    def shutdown(self):
        pass
''')

            # 热更新
            result = self.registry.hot_reload('reloadable')
            self.assertTrue(result)

            agent2 = self.registry.get('reloadable')
            self.assertEqual(agent2.VERSION, 2)
        finally:
            # 清理路径
            if temp_brain_py in sys.path:
                sys.path.remove(temp_brain_py)

    def test_hot_reload_not_found(self):
        """测试热更新不存在的策略"""
        result = self.registry.hot_reload('nonexistent')
        self.assertFalse(result)


class TestModuleLoading(TestCase):
    """测试模块加载"""

    def setUp(self):
        self.registry = AgentRegistry()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        self.registry.clear()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_from_module_file(self):
        """测试从文件加载模块"""
        module_path = os.path.join(self.temp_dir, 'test_module.py')
        with open(module_path, 'w') as f:
            f.write('''
from agent_registry import BaseAgent, AgentMetadata

class TestModuleAgent(BaseAgent):
    METADATA = {
        'version': '1.2.3',
        'description': 'Module test agent',
        'author': 'tester',
        'priority': 3,
        'tags': ['module', 'test']
    }

    def initialize(self):
        return True

    def predict(self, state):
        return {'result': 'ok'}

    def shutdown(self):
        pass
''')

        success = self.registry.load_from_module(module_path)

        self.assertTrue(success)

        info = self.registry.get_info('TestModuleAgent')
        self.assertIsNotNone(info)
        self.assertEqual(info.metadata.version, '1.2.3')
        self.assertEqual(info.metadata.author, 'tester')
        self.assertEqual(info.metadata.priority, StrategyPriority.HIGH)

    def test_load_from_module_with_class_name(self):
        """测试指定类名加载"""
        module_path = os.path.join(self.temp_dir, 'multi_agent.py')
        with open(module_path, 'w') as f:
            f.write('''
from agent_registry import BaseAgent

class AgentA(BaseAgent):
    def initialize(self): return True
    def predict(self, state): return 'A'
    def shutdown(self): pass

class AgentB(BaseAgent):
    def initialize(self): return True
    def predict(self, state): return 'B'
    def shutdown(self): pass
''')

        success = self.registry.load_from_module(module_path, 'AgentB', 'my_agent')

        self.assertTrue(success)

        agent = self.registry.get('my_agent')
        self.assertIsNotNone(agent)
        self.assertEqual(agent.predict(None), 'B')

    def test_load_from_module_not_found(self):
        """测试加载不存在的模块"""
        result = self.registry.load_from_module('/nonexistent/path.py')
        self.assertFalse(result)

    def test_load_from_module_no_agent_class(self):
        """测试模块中没有策略类"""
        module_path = os.path.join(self.temp_dir, 'no_agent.py')
        with open(module_path, 'w') as f:
            f.write('''
# No agent class here
def some_function():
    pass
''')

        result = self.registry.load_from_module(module_path)
        self.assertFalse(result)


class TestThreadSafety(TestCase):
    """测试线程安全"""

    def setUp(self):
        self.registry = AgentRegistry()

    def tearDown(self):
        self.registry.clear()

    def test_concurrent_register(self):
        """测试并发注册"""
        results = []

        def register_agent(i):
            agent = MockAgent()
            success = self.registry.register(f'agent_{i}', agent)
            results.append(success)

        threads = [threading.Thread(target=register_agent, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        self.assertEqual(len(self.registry.list_agents()), 10)

    def test_concurrent_get(self):
        """测试并发获取"""
        agent = MockAgent()
        self.registry.register('shared_agent', agent)

        results = []

        def get_agent():
            for _ in range(100):
                a = self.registry.get('shared_agent')
                if a:
                    results.append(a.predict(None))

        threads = [threading.Thread(target=get_agent) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 500)


class TestGlobalRegistry(TestCase):
    """测试全局注册表"""

    def test_get_global_registry(self):
        """测试获取全局注册表"""
        reg1 = get_global_registry()
        reg2 = get_global_registry()

        self.assertIs(reg1, reg2)


if __name__ == '__main__':
    main()
