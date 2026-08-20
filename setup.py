"""SmartPort-MultiAgent 安装配置。"""
from pathlib import Path

from setuptools import find_packages, setup

README = Path(__file__).parent / "README.md"

setup(
    name="smartport-multiagent",
    version="0.2.0",
    description="Multi-agent intelligent scheduling system for container "
                "terminals: berth allocation, quay crane scheduling, yard "
                "planning and LLM-enhanced conflict resolution",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="SmartPort-MultiAgent Contributors",
    license="MIT",
    packages=find_packages(include=["smartport", "smartport.*"]),
    python_requires=">=3.10",
    install_requires=[
        "pydantic>=2.0",
        "numpy>=1.24",
        "matplotlib>=3.7",
    ],
    extras_require={
        "solver": ["pulp>=2.7"],
        "exact": ["scipy>=1.9"],
        "dev": ["pytest>=7.0", "flake8>=6.0", "pulp>=2.7", "scipy>=1.9"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Operations Research",
    ],
    keywords="container terminal, berth allocation, multi-agent, "
             "scheduling, NSGA-II, MIP, LLM",
)
