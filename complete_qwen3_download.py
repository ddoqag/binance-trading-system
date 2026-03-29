#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完成 Qwen3-8B 模型下载（使用已存在的文件）
"""

from modelscope import snapshot_download
from pathlib import Path
import shutil

def complete_or_re_download():
    """完成下载或重新下载"""

    model_dir = Path("D:/binance/models")
    model_dir.mkdir(parents=True, exist_ok=True)

    # 检查现有文件
    existing_path = model_dir / "Qwen" / "Qwen3-8B"

    if existing_path.exists():
        print(f"发现已存在的模型目录: {existing_path}")
        files = list(existing_path.iterdir())
        print(f"现有文件数量: {len(files)}")

        # 检查是否有 safetensors 文件
        safetensors_files = list(existing_path.glob("*.safetensors"))
        if safetensors_files:
            print(f"发现 {len(safetensors_files)} 个 safetensors 文件:")
            for f in safetensors_files:
                size_gb = f.stat().st_size / 1024 / 1024 / 1024
                print(f"  - {f.name} ({size_gb:.2f} GB)")
        else:
            print("未发现 safetensors 模型文件，需要重新下载")

    print("\n" + "="*60)
    print("开始下载 Qwen/Qwen3-8B 模型...")
    print("="*60)

    try:
        model_path = snapshot_download(
            "Qwen/Qwen3-8B",
            cache_dir=str(model_dir),
            revision='master'
        )

        print(f"\n✓ 下载完成!")
        print(f"模型路径: {model_path}")

        # 列出所有文件
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
        return None

if __name__ == "__main__":
    complete_or_re_download()
