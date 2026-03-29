#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 ModelScope 下载 Qwen3-8B 模型
"""

from modelscope import snapshot_download
from pathlib import Path

def download_model():
    """下载 Qwen3-8B 模型"""

    # 创建目录
    model_dir = Path("D:/binance/models")
    model_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Qwen3-8B 模型下载工具 (ModelScope)")
    print("=" * 60)

    model_name = "Qwen/Qwen3-8B"

    print(f"\n正在下载: {model_name}")
    print(f"保存位置: {model_dir}")
    print("\n请稍候，模型较大 (约18GB)...\n")

    try:
        # 下载模型
        model_path = snapshot_download(
            model_name,
            cache_dir=str(model_dir),
            revision='master'
        )

        print("\n" + "=" * 60)
        print("下载成功!")
        print("=" * 60)
        print(f"\n模型路径: {model_path}")

        # 列出文件
        print("\n下载的文件:")
        total_size = 0
        for f in sorted(Path(model_path).iterdir()):
            if f.is_file():
                size_mb = f.stat().st_size / 1024 / 1024
                total_size += size_mb
                print(f"  - {f.name} ({size_mb:.2f} MB)")

        print(f"\n总大小: {total_size:.2f} MB ({total_size/1024:.2f} GB)")

        return model_path

    except Exception as e:
        print(f"\n下载失败: {e}")
        print("\n请尝试:")
        print("1. 检查网络连接")
        print("2. 手动访问: https://www.modelscope.cn/models/Qwen/Qwen3-8B")
        return None

if __name__ == "__main__":
    download_model()
