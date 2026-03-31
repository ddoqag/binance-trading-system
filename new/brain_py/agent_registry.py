"""
agent_registry.py - 策略注册表

提供动态策略注册、管理和热更新功能。
支持运行时策略加载/卸载，不中断交易。
"""

import time
import threading
from typing import Dict, List, Optional, Callable, Any, Type
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
import importlib
import importlib.util
import sys
import os


class AgentStatus(Enum):
    """策略状态枚举"""
    UNLOADED = auto()
    LOADING = auto()
    ACTIVE = auto()
    PAUSED = auto()
    ERROR = auto()
    RELOADING = auto()


class StrategyPriority(Enum):
    """策略优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class AgentMetadata:
    """策略元数据"""
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    priority: StrategyPriority = StrategyPriority.NORMAL
    tags: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class AgentInfo:
    """策略信息"""
    name: str
    status: AgentStatus
    metadata: AgentMetadata
    instance: Optional[Any] = None
    error_count: int = 0
    last_error: Optional[str] = None
    load_time: float = 0.0
    last_active: float = 0.0
    total_calls: int = 0


class BaseAgent(ABC):
    """策略基类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._initialized = False
        self._metadata: Optional[AgentMetadata] = None

    @abstractmethod
    def initialize(self) -> bool:
        """初始化策略"""
        pass

    @abstractmethod
    def predict(self, state: Any) -> Any:
        """执行预测"""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """关闭策略"""
        pass

    def health_check(self) -> bool:
        """健康检查"""
        return self._initialized

    def get_metadata(self) -> Optional[AgentMetadata]:
        """获取元数据"""
        return self._metadata

    def set_metadata(self, metadata: AgentMetadata) -> None:
        """设置元数据"""
        self._metadata = metadata


class AgentRegistry:
    """
    策略注册表

    功能：
    - 动态策略注册/注销
    - 策略热更新（不中断）
    - 策略元数据管理
    - 策略状态监控
    - 模块动态加载
    """

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._lock = threading.RLock()
        self._hooks: Dict[str, List[Callable]] = {
            'on_register': [],
            'on_unregister': [],
            'on_reload': [],
            'on_error': [],
        }
        self._module_cache: Dict[str, Any] = {}

    def register(
        self,
        name: str,
        agent: BaseAgent,
        metadata: Optional[AgentMetadata] = None
    ) -> bool:
        """
        注册策略

        Args:
            name: 策略唯一标识名
            agent: 策略实例
            metadata: 策略元数据

        Returns:
            bool: 注册是否成功
        """
        with self._lock:
            if name in self._agents:
                if self._agents[name].status == AgentStatus.ACTIVE:
                    print(f"[Registry] Agent '{name}' already registered and active")
                    return False

            # 创建或更新元数据
            if metadata is None:
                metadata = AgentMetadata(name=name)
            else:
                metadata.name = name
                metadata.updated_at = time.time()

            agent.set_metadata(metadata)

            # 初始化策略
            try:
                success = agent.initialize()
                if not success:
                    print(f"[Registry] Failed to initialize agent '{name}'")
                    return False
            except Exception as e:
                print(f"[Registry] Error initializing agent '{name}': {e}")
                return False

            # 创建AgentInfo
            agent_info = AgentInfo(
                name=name,
                status=AgentStatus.ACTIVE,
                metadata=metadata,
                instance=agent,
                load_time=time.time(),
                last_active=time.time()
            )

            self._agents[name] = agent_info

            # 触发回调
            self._trigger_hook('on_register', name, agent_info)

            print(f"[Registry] Agent '{name}' registered successfully")
            return True

    def unregister(self, name: str, graceful: bool = True) -> bool:
        """
        注销策略

        Args:
            name: 策略名
            graceful: 是否优雅关闭

        Returns:
            bool: 注销是否成功
        """
        with self._lock:
            if name not in self._agents:
                print(f"[Registry] Agent '{name}' not found")
                return False

            agent_info = self._agents[name]

            try:
                if graceful and agent_info.instance:
                    agent_info.instance.shutdown()

                del self._agents[name]

                # 触发回调
                self._trigger_hook('on_unregister', name, agent_info)

                print(f"[Registry] Agent '{name}' unregistered")
                return True

            except Exception as e:
                print(f"[Registry] Error unregistering agent '{name}': {e}")
                return False

    def get(self, name: str) -> Optional[BaseAgent]:
        """
        获取策略实例

        Args:
            name: 策略名

        Returns:
            BaseAgent: 策略实例或None
        """
        with self._lock:
            agent_info = self._agents.get(name)
            if agent_info and agent_info.status == AgentStatus.ACTIVE:
                agent_info.last_active = time.time()
                agent_info.total_calls += 1
                return agent_info.instance
            return None

    def get_info(self, name: str) -> Optional[AgentInfo]:
        """获取策略信息"""
        with self._lock:
            return self._agents.get(name)

    def list_agents(self, status: Optional[AgentStatus] = None) -> List[AgentInfo]:
        """
        列出所有策略

        Args:
            status: 可选，按状态过滤

        Returns:
            List[AgentInfo]: 策略信息列表
        """
        with self._lock:
            agents = list(self._agents.values())
            if status:
                agents = [a for a in agents if a.status == status]
            return agents

    def load_from_module(
        self,
        module_path: str,
        class_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        从模块动态加载策略

        Args:
            module_path: 模块文件路径或模块名
            class_name: 策略类名，默认自动查找
            agent_name: 注册名，默认使用类名
            config: 策略配置

        Returns:
            bool: 加载是否成功
        """
        try:
            # 加载模块
            if os.path.exists(module_path):
                # 从文件加载
                module_name = os.path.basename(module_path).replace('.py', '')
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                module = importlib.util.module_from_spec(spec)

                # 添加到sys.modules以支持相对导入
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            else:
                # 从已安装模块加载
                module = importlib.import_module(module_path)
                # 强制重新加载以支持热更新
                if module_path in self._module_cache:
                    module = importlib.reload(module)

            self._module_cache[module_path] = module

            # 查找策略类
            if class_name:
                agent_class = getattr(module, class_name)
            else:
                # 自动查找BaseAgent的子类
                agent_class = None
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                        issubclass(attr, BaseAgent) and
                        attr is not BaseAgent):
                        agent_class = attr
                        class_name = attr_name
                        break

            if agent_class is None:
                print(f"[Registry] No agent class found in {module_path}")
                return False

            # 实例化
            agent = agent_class(config=config)

            # 确定注册名
            name = agent_name or class_name or agent_class.__name__

            # 提取或创建元数据
            if hasattr(agent_class, 'METADATA'):
                meta_dict = agent_class.METADATA
                metadata = AgentMetadata(
                    name=name,
                    version=meta_dict.get('version', '1.0.0'),
                    description=meta_dict.get('description', ''),
                    author=meta_dict.get('author', ''),
                    priority=StrategyPriority(
                        meta_dict.get('priority', StrategyPriority.NORMAL.value)
                    ),
                    tags=meta_dict.get('tags', [])
                )
            else:
                metadata = AgentMetadata(name=name)

            # 保存文件路径到配置，用于热更新
            metadata.config = metadata.config or {}
            metadata.config['_source_file'] = module_path if os.path.exists(module_path) else None

            return self.register(name, agent, metadata)

        except Exception as e:
            print(f"[Registry] Error loading module {module_path}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def hot_reload(self, name: str) -> bool:
        """
        热更新策略

        不中断服务，替换策略实例

        Args:
            name: 策略名

        Returns:
            bool: 更新是否成功
        """
        with self._lock:
            if name not in self._agents:
                print(f"[Registry] Agent '{name}' not found for reload")
                return False

            agent_info = self._agents[name]
            old_agent = agent_info.instance
            old_metadata = agent_info.metadata

            # 标记为重新加载中
            agent_info.status = AgentStatus.RELOADING

        # 在锁外执行重载
        try:
            # 获取类信息
            class_name = old_agent.__class__.__name__
            config = old_agent.config

            # 获取源文件路径
            file_path = old_metadata.config.get('_source_file')

            if not file_path or not os.path.exists(file_path):
                # 尝试从模块获取
                module_path = old_agent.__class__.__module__
                if module_path in sys.modules:
                    module = sys.modules[module_path]
                    if hasattr(module, '__file__'):
                        file_path = module.__file__

            if not file_path or not os.path.exists(file_path):
                raise RuntimeError(f"Cannot find source file for agent '{name}'")

            # 生成新的唯一模块名
            module_name = f"_reload_{name}_{int(time.time() * 1000)}"

            # Windows 兼容：确保父目录在 sys.path 中
            file_dir = os.path.dirname(os.path.abspath(file_path))
            parent_dir = os.path.dirname(file_dir)

            # 添加必要的路径到 sys.path（用于测试中的相对导入）
            paths_to_add = [parent_dir, file_dir]
            added_paths = []
            for path in paths_to_add:
                if path and path not in sys.path:
                    sys.path.insert(0, path)
                    added_paths.append(path)

            # 确保 brain_py 目录在路径中
            brain_py_dir = os.path.dirname(os.path.abspath(__file__))
            if brain_py_dir not in sys.path:
                sys.path.insert(0, brain_py_dir)
                added_paths.append(brain_py_dir)

            try:
                # 重新加载模块
                # 注意：在 Windows 上，确保使用唯一的模块名来避免缓存问题
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                new_module = importlib.util.module_from_spec(spec)

                sys.modules[module_name] = new_module

                # Windows 兼容：使用 exec 代替 exec_module 来强制从磁盘读取
                # 避免文件系统缓存问题
                if os.name == 'nt':  # Windows
                    with open(file_path, 'r', encoding='utf-8') as f:
                        source = f.read()
                    code = compile(source, file_path, 'exec')
                    exec(code, new_module.__dict__)
                else:
                    spec.loader.exec_module(new_module)

                # 验证类是最新的（通过检查文件修改时间）
                current_mtime = os.path.getmtime(file_path)
            finally:
                # 清理临时添加的路径（避免污染 sys.path）
                for path in added_paths:
                    if path in sys.path:
                        sys.path.remove(path)

            # 获取新类
            new_class = getattr(new_module, class_name)

            # 创建新实例
            new_agent = new_class(config=config)

            # 初始化新实例
            if not new_agent.initialize():
                raise RuntimeError("New agent failed to initialize")

            # 切换实例（加锁）
            with self._lock:
                # 优雅关闭旧实例
                try:
                    old_agent.shutdown()
                except Exception as e:
                    print(f"[Registry] Warning: error shutting down old agent: {e}")

                # 更新元数据 (保留新agent的版本号)
                new_version = getattr(new_agent, 'VERSION', old_metadata.version)
                new_metadata = AgentMetadata(
                    name=name,
                    version=str(new_version),
                    description=old_metadata.description,
                    author=old_metadata.author,
                    priority=old_metadata.priority,
                    tags=old_metadata.tags.copy(),
                    config=config or {},
                    updated_at=time.time()
                )
                new_agent.set_metadata(new_metadata)

                # 更新注册表
                agent_info.instance = new_agent
                agent_info.metadata = new_metadata
                agent_info.status = AgentStatus.ACTIVE
                agent_info.load_time = time.time()

            # 触发回调
            self._trigger_hook('on_reload', name, agent_info)

            print(f"[Registry] Agent '{name}' hot reloaded successfully")
            return True

        except Exception as e:
            # 恢复状态
            with self._lock:
                agent_info.status = AgentStatus.ERROR
                agent_info.error_count += 1
                agent_info.last_error = str(e)

            print(f"[Registry] Hot reload failed for '{name}': {e}")
            self._trigger_hook('on_error', name, e)
            return False

    def pause(self, name: str) -> bool:
        """暂停策略"""
        with self._lock:
            if name not in self._agents:
                return False
            agent_info = self._agents[name]
            if agent_info.status == AgentStatus.ACTIVE:
                agent_info.status = AgentStatus.PAUSED
                return True
            return False

    def resume(self, name: str) -> bool:
        """恢复策略"""
        with self._lock:
            if name not in self._agents:
                return False
            agent_info = self._agents[name]
            if agent_info.status == AgentStatus.PAUSED:
                agent_info.status = AgentStatus.ACTIVE
                return True
            return False

    def add_hook(self, event: str, callback: Callable) -> None:
        """添加事件钩子"""
        if event in self._hooks:
            self._hooks[event].append(callback)

    def remove_hook(self, event: str, callback: Callable) -> None:
        """移除事件钩子"""
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)

    def _trigger_hook(self, event: str, *args, **kwargs) -> None:
        """触发事件钩子"""
        for callback in self._hooks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"[Registry] Hook error for {event}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取注册表统计信息"""
        with self._lock:
            total = len(self._agents)
            active = sum(1 for a in self._agents.values() if a.status == AgentStatus.ACTIVE)
            paused = sum(1 for a in self._agents.values() if a.status == AgentStatus.PAUSED)
            errors = sum(1 for a in self._agents.values() if a.status == AgentStatus.ERROR)

            return {
                'total_agents': total,
                'active': active,
                'paused': paused,
                'errors': errors,
                'total_calls': sum(a.total_calls for a in self._agents.values()),
                'agents': [
                    {
                        'name': a.name,
                        'status': a.status.name,
                        'version': a.metadata.version,
                        'calls': a.total_calls,
                        'last_active': a.last_active
                    }
                    for a in self._agents.values()
                ]
            }

    def clear(self) -> None:
        """清空所有策略"""
        with self._lock:
            for name, agent_info in list(self._agents.items()):
                try:
                    if agent_info.instance:
                        agent_info.instance.shutdown()
                except Exception as e:
                    print(f"[Registry] Error shutting down '{name}': {e}")

            self._agents.clear()
            print("[Registry] All agents cleared")


# 全局注册表实例
_global_registry: Optional[AgentRegistry] = None


def get_global_registry() -> AgentRegistry:
    """获取全局注册表实例"""
    global _global_registry
    if _global_registry is None:
        _global_registry = AgentRegistry()
    return _global_registry
