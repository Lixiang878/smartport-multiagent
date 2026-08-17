"""配置加载：JSON 配置文件 → dict / Scenario。"""
from __future__ import annotations

import json
from pathlib import Path

from smartport.core.models import Scenario

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def load_json(path: str | Path) -> dict:
    """读取 JSON 配置文件。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_algorithm_config(
    path: str | Path | None = None,
) -> dict:
    """加载算法超参数配置（configs/algorithm.json）。"""
    p = Path(path) if path else DEFAULT_CONFIG_DIR / "algorithm.json"
    if not p.exists():
        return {}
    data = load_json(p)
    return data.get("algorithm", data)


def load_llm_config(path: str | Path | None = None) -> dict:
    """加载 LLM 配置（configs/llm.json；无密钥时自动纯规则模式）。"""
    p = Path(path) if path else DEFAULT_CONFIG_DIR / "llm.json"
    if not p.exists():
        return {}
    data = load_json(p)
    return data.get("llm", data)


def load_scenario(path: str | Path) -> Scenario:
    """加载算例配置文件为 Scenario。

    支持两种格式：
    - 显式算例：{"scenario": {...vessels/berths/cranes/blocks...}}；
    - 参数化生成：{"generate": {"n_vessels": 40, "seed": 7, ...}}。
    """
    from smartport.utils.instance_gen import generate_scenario

    data = load_json(path)
    if "generate" in data:
        return generate_scenario(**data["generate"])
    return Scenario.model_validate(data["scenario"])
