#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 ModelScope 下载 Qwen3.5 模型
"""

import os
import sys
from pathlib import Path

def install_dependencies():
    """安装必要的依赖"""
    import subprocess
    print("正在安装 ModelScope SDK...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "modelscope"])

def download_qwen35_model():
    """下载 Qwen3.5-7B 模型"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("需要先安装 ModelScope SDK")
        install_dependencies()
        from modelscope import snapshot_download

    # 创建模型存储目录
    model_dir = Path("D:/binance/models/gguf")
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"模型将下载到: {model_dir}")

    # 下载 Qwen3.5-7B 模型
    # 可用模型: Qwen/Qwen3.5-7B-Chat
    print("\n正在下载 Qwen3.5-7B-Chat 模型...")

    model_name = "Qwen/Qwen3.5-7B-Chat"

    try:
        # 下载模型
        model_path = snapshot_download(
            model_name,
            cache_dir=str(model_dir),
            revision='master'
        )

        print(f"\n✓ 模型下载成功!")
        print(f"模型路径: {model_path}")

        # 列出下载的文件
        print("\n下载的文件:")
        for f in Path(model_path).iterdir():
            if f.is_file():
                print(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")

        return model_path

    except Exception as e:
        print(f"\n✗ 下载失败: {e}")
        print("\n尝试手动访问 ModelScope 网站下载:")
        print("https://www.modelscope.cn/models/Qwen/Qwen3.5-7B-Chat")
        return None

def main():
    print("=" * 60)
    print("Qwen3.5 模型下载工具")
    print("=" * 60)

    # 选择模型类型
    print("\n可用模型:")
    print("1. Qwen3.5-7B-Chat (推荐)")
    print("2. Qwen2.5-7B-Chat (备选)")

    choice = input("\n请选择模型 (默认 1): ").strip() or "1"

    if choice == "1":
        model_name = "Qwen3.5-7B-Chat"
    elif choice == "2":
        model_name = "Qwen2.5-7B-Chat"
    else:
        print("无效选择，使用默认 Qwen3.5-7B-Chat")
        model_name = "Qwen3.5-7B-Chat"

    print(f"\n已选择: {model_name}")
    print("\n开始下载...")

    model_path = download_qwen35_model()

    if model_path:
        print("\n" + "=" * 60)
        print("下载完成!")
        print("=" * 60)
        print(f"\n下一步:")
        print("1. 如需量化为 GGUF 格式，可使用 llama.cpp")
        print("2. 或者直接使用 transformers 加载模型")
    else:
        print("\n" + "=" * 60)
        print("下载失败，请尝试手动下载")
        print("=" * 60)

if __name__ == "__main__":
    main()
