"""
Setup script for Python bindings.

Use maturin for building: pip install maturin && maturin develop
"""

from setuptools import setup, find_packages

setup(
    name="rust-execution",
    version="0.1.0",
    description="High-performance Rust execution engine for HFT",
    packages=find_packages(),
    python_requires=">=3.8",
    zip_safe=False,
)
