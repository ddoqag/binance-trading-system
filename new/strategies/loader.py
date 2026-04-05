"""
策略加载器 - 支持热插拔的动态策略加载

功能：
- 从目录加载策略
- 文件监控和热重载
- 批量注册到 AgentRegistry
"""

import os
import sys
import time
import threading
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, Any, Optional, List, Type, Callable
from dataclasses import dataclass

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# 导入 brain_py 组件
sys.path.insert(0, 'D:/binance/new')
from brain_py.agent_registry import AgentRegistry, BaseAgent, AgentMetadata, StrategyPriority, get_global_registry
from strategies.base import StrategyBase


@dataclass
class LoadedStrategy:
    """已加载的策略信息"""
    name: str
    class_type: Type[StrategyBase]
    file_path: str
    module: Any
    instance: Optional[StrategyBase] = None
    load_time: float = 0.0


class StrategyLoader:
    """
    策略加载器

    支持热插拔的动态策略加载系统
    """

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or get_global_registry()
        self._loaded: Dict[str, LoadedStrategy] = {}
        self._file_mtimes: Dict[str, float] = {}

        # 热重载支持
        self._observer: Optional[Observer] = None
        self._watch_paths: set = set()
        self._reload_callbacks: List[Callable] = []
        self._lock = threading.RLock()

    # ============ 核心加载方法 ============

    def load_from_file(
        self,
        file_path: str,
        strategy_name: Optional[str] = None,
        auto_reload: bool = False
    ) -> bool:
        """
        从文件加载策略

        Args:
            file_path: Python 文件路径
            strategy_name: 策略名称（默认使用类名）
            auto_reload: 是否启用热重载

        Returns:
            bool: 是否成功
        """
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            print(f"[Loader] File not found: {abs_path}")
            return False

        try:
            with self._lock:
                # 检查是否已加载
                if abs_path in self._file_mtimes:
                    print(f"[Loader] Strategy already loaded: {abs_path}")
                    return self._reload(abs_path)

                # 记录修改时间
                self._file_mtimes[abs_path] = os.path.getmtime(abs_path)

                # 加载模块
                module_name = f"_strategy_{Path(abs_path).stem}_{int(time.time() * 1000)}"
                spec = importlib.util.spec_from_file_location(module_name, abs_path)
                module = importlib.util.module_from_spec(spec)

                # 添加策略目录到 sys.path
                strategy_dir = os.path.dirname(abs_path)
                if strategy_dir not in sys.path:
                    sys.path.insert(0, strategy_dir)

                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 查找策略类
                strategy_class = self._find_strategy_class(module)

                if strategy_class is None:
                    print(f"[Loader] No StrategyBase subclass found in {abs_path}")
                    return False

                # 确定策略名称
                name = strategy_name or strategy_class.__name__

                # 保存加载信息
                self._loaded[name] = LoadedStrategy(
                    name=name,
                    class_type=strategy_class,
                    file_path=abs_path,
                    module=module,
                    load_time=time.time()
                )

                # 实例化并注册
                return self._register_strategy(name)

        except Exception as e:
            print(f"[Loader] Error loading {abs_path}: {e}")
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
            directory: 策略目录
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

        # 排除特殊文件和非策略文件
        excluded_files = {'base.py', 'loader.py', '__init__.py'}
        files = [f for f in files if not f.name.startswith('_') and f.name not in excluded_files]

        print(f"[Loader] Found {len(files)} strategy files in {directory}")

        for file_path in files:
            # 使用文件名作为策略名
            strategy_name = file_path.stem
            success = self.load_from_file(str(file_path), strategy_name)
            results[strategy_name] = success

        return results

    def unload(self, strategy_name: str) -> bool:
        """
        卸载策略

        Args:
            strategy_name: 策略名称

        Returns:
            bool: 是否成功
        """
        with self._lock:
            if strategy_name not in self._loaded:
                return False

            loaded = self._loaded[strategy_name]

            # 从 registry 注销
            self.registry.unregister(strategy_name, graceful=True)

            # 清理
            del self._loaded[strategy_name]
            if loaded.file_path in self._file_mtimes:
                del self._file_mtimes[loaded.file_path]

            print(f"[Loader] Unloaded strategy: {strategy_name}")
            return True

    def reload(self, strategy_name: str) -> bool:
        """
        热重载策略

        Args:
            strategy_name: 策略名称

        Returns:
            bool: 是否成功
        """
        with self._lock:
            if strategy_name not in self._loaded:
                print(f"[Loader] Strategy not found: {strategy_name}")
                return False

            loaded = self._loaded[strategy_name]
            return self._reload(loaded.file_path, strategy_name)

    def reload_all(self) -> Dict[str, bool]:
        """重载所有策略"""
        results = {}
        for name in list(self._loaded.keys()):
            results[name] = self.reload(name)
        return results

    def _reload(self, file_path: str, strategy_name: Optional[str] = None) -> bool:
        """内部重载实现"""
        try:
            abs_path = os.path.abspath(file_path)

            # 找到对应的策略名
            if strategy_name is None:
                for name, loaded in self._loaded.items():
                    if loaded.file_path == abs_path:
                        strategy_name = name
                        break

            if strategy_name is None:
                return False

            loaded = self._loaded[strategy_name]

            # 使用 registry 的热重载功能
            if strategy_name in [a.name for a in self.registry.list_agents()]:
                success = self.registry.hot_reload(strategy_name)
                if success:
                    loaded.load_time = time.time()
                    self._file_mtimes[abs_path] = os.path.getmtime(abs_path)
                    print(f"[Loader] Hot reloaded: {strategy_name}")
                    self._notify_reload(strategy_name)
                return success

            # 如果 registry 中没有，重新加载
            self.unload(strategy_name)
            return self.load_from_file(abs_path, strategy_name)

        except Exception as e:
            print(f"[Loader] Reload failed: {e}")
            return False

    def _register_strategy(self, name: str) -> bool:
        """注册策略到 registry"""
        loaded = self._loaded[name]

        try:
            # 实例化
            instance = loaded.class_type(config={})

            # 初始化
            if not instance.initialize():
                print(f"[Loader] Strategy initialization failed: {name}")
                return False

            loaded.instance = instance

            # 构建元数据
            metadata = self._build_metadata(instance, name)

            # 注册到 registry
            success = self.registry.register(name, instance, metadata)

            if success:
                print(f"[Loader] Registered strategy: {name}")

            return success

        except Exception as e:
            print(f"[Loader] Error registering {name}: {e}")
            return False

    def _build_metadata(self, instance: StrategyBase, name: str) -> AgentMetadata:
        """构建 AgentMetadata"""
        meta = instance.get_metadata()

        # 如果 instance 没有元数据，尝试从类属性获取
        if meta is None:
            if hasattr(instance, 'METADATA') and instance.METADATA is not None:
                meta = instance.METADATA
            else:
                # 使用默认元数据
                return AgentMetadata(
                    name=name,
                    version="1.0.0",
                    description=f"Strategy: {name}",
                    priority=StrategyPriority.NORMAL,
                    tags=[],
                    config={}
                )

        # 处理 AgentMetadata 类型（来自 BaseAgent 子类）
        if isinstance(meta, AgentMetadata):
            return meta

        # 处理 StrategyMetadata 类型（来自 StrategyBase 子类）
        # 转换 suitable_regimes 到 tags
        tags = list(meta.tags) if hasattr(meta, 'tags') else []
        if hasattr(meta, 'suitable_regimes'):
            for regime in meta.suitable_regimes:
                tags.append(f"regime:{regime}")

        return AgentMetadata(
            name=name,
            version=meta.version if hasattr(meta, 'version') else "1.0.0",
            description=meta.description if hasattr(meta, 'description') else "",
            author=meta.author if hasattr(meta, 'author') else "",
            priority=StrategyPriority.NORMAL,
            tags=tags,
            config=meta.params if hasattr(meta, 'params') else (meta.config if hasattr(meta, 'config') else {})
        )

    def _find_strategy_class(self, module: Any) -> Optional[Type[StrategyBase]]:
        """在模块中查找策略类（支持 StrategyBase 和 BaseAgent）"""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not isinstance(attr, type) or attr_name.startswith('_'):
                continue
            # 检查是否是 StrategyBase 或 BaseAgent 的子类
            if issubclass(attr, StrategyBase) and attr is not StrategyBase:
                return attr
            if issubclass(attr, BaseAgent) and attr is not BaseAgent:
                return attr
        return None

    # ============ 热重载监控 ============

    def start_file_watcher(self, check_interval: float = 1.0) -> bool:
        """
        启动文件监控

        Args:
            check_interval: 检查间隔（秒）

        Returns:
            bool: 是否成功启动
        """
        if not WATCHDOG_AVAILABLE:
            print("[Loader] watchdog not installed, using polling mode")
            return self._start_polling_watcher(check_interval)

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class ReloadHandler(FileSystemEventHandler):
                def __init__(self, loader: 'StrategyLoader'):
                    self.loader = loader

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    if not event.src_path.endswith('.py'):
                        return

                    abs_path = os.path.abspath(event.src_path)
                    with self.loader._lock:
                        for name, loaded in self.loader._loaded.items():
                            if loaded.file_path == abs_path:
                                print(f"[Loader] File changed: {abs_path}")
                                self.loader.reload(name)
                                break

            self._observer = Observer()

            # 监控所有已加载策略的目录
            watched_dirs = set()
            for loaded in self._loaded.values():
                dir_path = os.path.dirname(loaded.file_path)
                if dir_path not in watched_dirs:
                    handler = ReloadHandler(self)
                    self._observer.schedule(handler, dir_path, recursive=False)
                    watched_dirs.add(dir_path)

            self._observer.start()
            print(f"[Loader] File watcher started ({len(watched_dirs)} directories)")
            return True

        except Exception as e:
            print(f"[Loader] Failed to start file watcher: {e}")
            return self._start_polling_watcher(check_interval)

    def _start_polling_watcher(self, check_interval: float) -> bool:
        """使用轮询模式监控文件变化"""
        def watch_loop():
            while True:
                time.sleep(check_interval)
                self._check_for_changes()

        thread = threading.Thread(target=watch_loop, daemon=True)
        thread.start()
        print(f"[Loader] Polling watcher started (interval: {check_interval}s)")
        return True

    def _check_for_changes(self):
        """检查文件变化"""
        with self._lock:
            for file_path, last_mtime in list(self._file_mtimes.items()):
                if os.path.exists(file_path):
                    current_mtime = os.path.getmtime(file_path)
                    if current_mtime > last_mtime:
                        # 找到对应的策略并重载
                        for name, loaded in self._loaded.items():
                            if loaded.file_path == file_path:
                                print(f"[Loader] Detected change (polling): {file_path}")
                                self._reload(file_path, name)
                                break

    def stop_file_watcher(self):
        """停止文件监控"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            print("[Loader] File watcher stopped")

    def on_reload(self, callback: Callable[[str], None]):
        """
        注册重载回调

        Args:
            callback: 回调函数，接收策略名称参数
        """
        self._reload_callbacks.append(callback)

    def _notify_reload(self, strategy_name: str):
        """通知重载事件"""
        for callback in self._reload_callbacks:
            try:
                callback(strategy_name)
            except Exception as e:
                print(f"[Loader] Reload callback error: {e}")

    # ============ 查询方法 ============

    def get_loaded_strategies(self) -> List[str]:
        """获取已加载的策略列表"""
        return list(self._loaded.keys())

    def get_strategy_info(self, name: str) -> Optional[LoadedStrategy]:
        """获取策略信息"""
        return self._loaded.get(name)

    def get_stats(self) -> Dict[str, Any]:
        """获取加载器统计信息"""
        return {
            'loaded_count': len(self._loaded),
            'watched_files': len(self._file_mtimes),
            'strategies': [
                {
                    'name': name,
                    'class': loaded.class_type.__name__,
                    'file': loaded.file_path,
                    'load_time': loaded.load_time
                }
                for name, loaded in self._loaded.items()
            ]
        }

    def clear(self):
        """清空所有加载的策略"""
        with self._lock:
            for name in list(self._loaded.keys()):
                self.unload(name)
            self._loaded.clear()
            self._file_mtimes.clear()


# ============ 全局实例 ============

_loader_instance: Optional[StrategyLoader] = None


def get_strategy_loader(registry: Optional[AgentRegistry] = None) -> StrategyLoader:
    """获取全局策略加载器实例"""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = StrategyLoader(registry)
    return _loader_instance


def load_all_strategies(
    directory: str = "strategies",
    registry: Optional[AgentRegistry] = None
) -> Dict[str, bool]:
    """
    加载目录中的所有策略

    Args:
        directory: 策略目录
        registry: AgentRegistry 实例

    Returns:
        Dict[str, bool]: 策略名称到成功状态的映射
    """
    loader = get_strategy_loader(registry)
    return loader.load_from_directory(directory)
