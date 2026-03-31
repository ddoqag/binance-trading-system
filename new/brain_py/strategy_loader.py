"""
strategy_loader.py - 策略加载器

提供策略的动态发现、加载和热更新功能。
支持文件系统监控、自动重载和批量加载。
"""

import os
import sys
import time
import threading
import importlib
import importlib.util
from typing import Dict, List, Optional, Type, Any, Callable
from pathlib import Path
from dataclasses import dataclass, field
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

try:
    from .agent_registry import (
        AgentRegistry, BaseAgent, AgentMetadata,
        StrategyPriority, AgentStatus, get_global_registry
    )
except ImportError:
    from agent_registry import (
        AgentRegistry, BaseAgent, AgentMetadata,
        StrategyPriority, AgentStatus, get_global_registry
    )


@dataclass
class StrategySpec:
    """策略规格"""
    name: str
    module_path: str
    class_name: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    auto_reload: bool = False
    dependencies: List[str] = field(default_factory=list)


class StrategyModuleLoader:
    """
    策略模块加载器

    负责从文件系统加载策略模块
    """

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or get_global_registry()
        self._loaded_modules: Dict[str, Any] = {}
        self._module_mtimes: Dict[str, float] = {}

    def load_from_file(
        self,
        file_path: str,
        class_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        从文件加载策略

        Args:
            file_path: Python文件路径
            class_name: 类名，None则自动查找
            agent_name: 注册名，None则使用类名
            config: 配置字典

        Returns:
            bool: 是否成功
        """
        if not os.path.exists(file_path):
            print(f"[Loader] File not found: {file_path}")
            return False

        try:
            # 记录修改时间
            self._module_mtimes[file_path] = os.path.getmtime(file_path)

            # 加载模块
            module_name = self._get_module_name(file_path)
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)

            # 添加到sys.modules
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self._loaded_modules[file_path] = module

            # 查找策略类
            if class_name:
                agent_class = getattr(module, class_name)
            else:
                agent_class = self._find_agent_class(module)

            if agent_class is None:
                print(f"[Loader] No agent class found in {file_path}")
                return False

            # 实例化并注册
            agent = agent_class(config=config)
            name = agent_name or agent_class.__name__

            metadata = self._extract_metadata(agent_class, name)

            return self.registry.register(name, agent, metadata)

        except Exception as e:
            print(f"[Loader] Error loading {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_from_directory(
        self,
        directory: str,
        pattern: str = "*.py",
        recursive: bool = False
    ) -> Dict[str, bool]:
        """
        从目录批量加载策略

        Args:
            directory: 目录路径
            pattern: 文件匹配模式
            recursive: 是否递归子目录

        Returns:
            Dict[str, bool]: 文件名到成功状态的映射
        """
        results = {}
        path = Path(directory)

        if not path.exists():
            print(f"[Loader] Directory not found: {directory}")
            return results

        # 查找文件
        if recursive:
            files = list(path.rglob(pattern))
        else:
            files = list(path.glob(pattern))

        # 排除__init__.py等
        files = [f for f in files if not f.name.startswith('_')]

        print(f"[Loader] Found {len(files)} strategy files in {directory}")

        for file_path in files:
            # 从文件名推断策略名
            agent_name = file_path.stem
            success = self.load_from_file(
                str(file_path),
                agent_name=agent_name
            )
            results[file_path.name] = success

        return results

    def reload_module(self, file_path: str) -> bool:
        """重新加载模块"""
        if file_path not in self._loaded_modules:
            print(f"[Loader] Module not loaded: {file_path}")
            return False

        # 找到对应的agent名
        agent_name = None
        for info in self.registry.list_agents():
            if info.metadata.config.get('file_path') == file_path:
                agent_name = info.name
                break

        if agent_name:
            return self.registry.hot_reload(agent_name)

        # 如果找不到agent名，重新加载
        return self.load_from_file(file_path)

    def check_for_updates(self) -> List[str]:
        """
        检查已加载模块是否有更新

        Returns:
            List[str]: 有更新的文件路径列表
        """
        updated = []
        for file_path, last_mtime in self._module_mtimes.items():
            if os.path.exists(file_path):
                current_mtime = os.path.getmtime(file_path)
                if current_mtime > last_mtime:
                    updated.append(file_path)
                    self._module_mtimes[file_path] = current_mtime
        return updated

    def _get_module_name(self, file_path: str) -> str:
        """从文件路径生成模块名"""
        path = Path(file_path)
        return f"_strategy_{path.stem}_{int(time.time())}"

    def _find_agent_class(self, module: Any) -> Optional[Type[BaseAgent]]:
        """在模块中查找策略类"""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                issubclass(attr, BaseAgent) and
                attr is not BaseAgent):
                return attr
        return None

    def _extract_metadata(
        self,
        agent_class: Type[BaseAgent],
        name: str
    ) -> AgentMetadata:
        """从类中提取元数据"""
        if hasattr(agent_class, 'METADATA'):
            meta = agent_class.METADATA
            return AgentMetadata(
                name=name,
                version=meta.get('version', '1.0.0'),
                description=meta.get('description', ''),
                author=meta.get('author', ''),
                priority=StrategyPriority(
                    meta.get('priority', StrategyPriority.NORMAL.value)
                ),
                tags=meta.get('tags', [])
            )
        return AgentMetadata(name=name)


class AutoReloader(FileSystemEventHandler):
    """
    自动重载处理器

    监控文件变化并自动重载策略
    """

    def __init__(
        self,
        loader: StrategyModuleLoader,
        registry: Optional[AgentRegistry] = None
    ):
        self.loader = loader
        self.registry = registry or get_global_registry()
        self._watched_paths: Dict[str, str] = {}  # path -> agent_name
        self._pending_reload: set = set()
        self._lock = threading.Lock()

    def watch(self, file_path: str, agent_name: Optional[str] = None) -> None:
        """添加监控路径"""
        abs_path = os.path.abspath(file_path)
        self._watched_paths[abs_path] = agent_name or Path(abs_path).stem

    def unwatch(self, file_path: str) -> None:
        """移除监控路径"""
        abs_path = os.path.abspath(file_path)
        if abs_path in self._watched_paths:
            del self._watched_paths[abs_path]

    def on_modified(self, event):
        """文件修改回调"""
        if event.is_directory:
            return

        if not event.src_path.endswith('.py'):
            return

        abs_path = os.path.abspath(event.src_path)

        with self._lock:
            if abs_path in self._watched_paths:
                self._pending_reload.add(abs_path)

    def process_pending(self) -> Dict[str, bool]:
        """处理待重载的文件"""
        results = {}

        with self._lock:
            pending = self._pending_reload.copy()
            self._pending_reload.clear()

        for file_path in pending:
            agent_name = self._watched_paths.get(file_path)

            if agent_name:
                # 使用热更新
                success = self.registry.hot_reload(agent_name)
                results[agent_name] = success
            else:
                # 重新加载
                success = self.loader.load_from_file(file_path)
                results[file_path] = success

        return results


class StrategyLoader:
    """
    策略加载器主类

    整合模块加载、自动重载和批量管理功能
    """

    def __init__(
        self,
        registry: Optional[AgentRegistry] = None,
        enable_auto_reload: bool = False
    ):
        self.registry = registry or get_global_registry()
        self.module_loader = StrategyModuleLoader(self.registry)
        self.auto_reload = enable_auto_reload

        self._observer: Optional[Observer] = None
        self._reloader: Optional[AutoReloader] = None
        self._reload_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def load(
        self,
        spec: StrategySpec
    ) -> bool:
        """
        加载策略

        Args:
            spec: 策略规格

        Returns:
            bool: 是否成功
        """
        success = self.module_loader.load_from_file(
            spec.module_path,
            spec.class_name,
            spec.name,
            spec.config
        )

        if success and spec.auto_reload:
            self._enable_watch(spec.module_path, spec.name)

        return success

    def load_batch(
        self,
        specs: List[StrategySpec]
    ) -> Dict[str, bool]:
        """批量加载策略"""
        results = {}
        for spec in specs:
            results[spec.name] = self.load(spec)
        return results

    def load_directory(
        self,
        directory: str,
        pattern: str = "*_strategy.py",
        recursive: bool = False
    ) -> Dict[str, bool]:
        """从目录加载所有策略"""
        return self.module_loader.load_from_directory(
            directory, pattern, recursive
        )

    def start_auto_reload(
        self,
        check_interval: float = 1.0
    ) -> None:
        """
        启动自动重载

        Args:
            check_interval: 检查间隔（秒）
        """
        if self._reload_thread is not None:
            return

        self._stop_event.clear()

        def reload_loop():
            while not self._stop_event.is_set():
                # 检查文件更新
                updated = self.module_loader.check_for_updates()
                for file_path in updated:
                    print(f"[Loader] Detected change: {file_path}")
                    self.module_loader.reload_module(file_path)

                # 处理待处理的重载（来自文件监控）
                if self._reloader:
                    self._reloader.process_pending()

                self._stop_event.wait(check_interval)

        self._reload_thread = threading.Thread(target=reload_loop, daemon=True)
        self._reload_thread.start()

        print(f"[Loader] Auto-reload started (interval: {check_interval}s)")

    def stop_auto_reload(self) -> None:
        """停止自动重载"""
        self._stop_event.set()

        if self._reload_thread:
            self._reload_thread.join(timeout=2.0)
            self._reload_thread = None

        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

        print("[Loader] Auto-reload stopped")

    def start_file_watcher(
        self,
        watch_paths: List[str]
    ) -> None:
        """
        启动文件系统监控

        Args:
            watch_paths: 要监控的目录列表
        """
        if self._observer is not None:
            return

        self._reloader = AutoReloader(self.module_loader, self.registry)

        self._observer = Observer()
        for path in watch_paths:
            if os.path.exists(path):
                self._observer.schedule(self._reloader, path, recursive=True)
                print(f"[Loader] Watching: {path}")

        self._observer.start()

    def _enable_watch(
        self,
        file_path: str,
        agent_name: str
    ) -> None:
        """启用文件监控"""
        if self._reloader is None:
            self._reloader = AutoReloader(self.module_loader, self.registry)

        self._reloader.watch(file_path, agent_name)

        # 确保目录被监控
        if self._observer is None:
            directory = os.path.dirname(file_path)
            self.start_file_watcher([directory])

    def unload(self, name: str) -> bool:
        """卸载策略"""
        return self.registry.unregister(name)

    def unload_all(self) -> None:
        """卸载所有策略"""
        self.registry.clear()

    def get_status(self) -> Dict[str, Any]:
        """获取加载器状态"""
        return {
            'auto_reload': self.auto_reload,
            'watched_modules': len(self.module_loader._loaded_modules),
            'registry_stats': self.registry.get_stats()
        }


def create_strategy_from_config(
    config: Dict[str, Any],
    registry: Optional[AgentRegistry] = None
) -> bool:
    """
    从配置创建策略

    配置格式:
    {
        'name': 'my_strategy',
        'module': 'path/to/strategy.py',
        'class': 'MyStrategy',  # 可选
        'config': {...},  # 可选
        'auto_reload': False  # 可选
    }
    """
    loader = StrategyLoader(registry)

    spec = StrategySpec(
        name=config['name'],
        module_path=config['module'],
        class_name=config.get('class'),
        config=config.get('config', {}),
        auto_reload=config.get('auto_reload', False)
    )

    return loader.load(spec)
