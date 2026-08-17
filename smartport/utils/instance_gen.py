"""标准算例生成与文献算例接口。

generate_scenario()：参数化生成港口算例（船舶聚簇到港模拟高峰期），
配置驱动（configs/*.json 的 "generate" 段）。

文献算例接口：load_literature_instance() 支持加载公开文献 BAP 算例
（JSON/CSV 转录格式，见 configs/literature/README.md），便于学术对比实验。
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

from smartport.core.models import (
    Berth,
    Container,
    ContainerBlock,
    QuayCrane,
    Scenario,
    Vessel,
)

# 船型参数：length/draft 范围与 moves 范围
VESSEL_SIZE_PARAMS: dict[str, dict] = {
    "feeder": {"length": (120, 180), "draft": (7.0, 9.0), "moves": (120, 260)},
    "medium": {"length": (200, 280), "draft": (10.0, 12.0), "moves": (260, 520)},
    "large": {"length": (300, 350), "draft": (13.0, 15.0), "moves": (520, 900)},
}
SIZE_WEIGHTS: dict[str, list[float]] = {
    "small_port": [0.5, 0.4, 0.1],
    "large_port": [0.4, 0.4, 0.2],
}
# 泊位规格（长度, 水深）
BERTH_SPECS: list[tuple[float, float]] = [
    (280.0, 12.0), (320.0, 13.0), (360.0, 14.0), (400.0, 15.0), (420.0, 16.0),
]
PRIORITY_WEIGHTS: list[tuple[int, float]] = [(1, 0.1), (2, 0.2), (3, 0.4), (4, 0.2), (5, 0.1)]
DESTINATIONS = ["CNSHA", "SGSIN", "JPTYO", "USLAX", "DEHAM", "MYPKG"]
WEIGHT_CLASSES = ["light", "medium", "heavy"]


def _weighted_choice(rng: random.Random, pairs: list[tuple]) -> object:
    r = rng.random()
    acc = 0.0
    for value, w in pairs:
        acc += w
        if r <= acc:
            return value
    return pairs[-1][0]


def _make_berths(n: int) -> list[Berth]:
    """泊位沿岸线排布：position 累计，间隔 40m 安全距。"""
    berths: list[Berth] = []
    pos = 0.0
    for i in range(n):
        length, depth = BERTH_SPECS[i % len(BERTH_SPECS)]
        berths.append(Berth(
            id=f"B{i + 1}", name=f"Berth-{i + 1}",
            length_m=length, depth_m=depth, position_m=pos,
        ))
        pos += length + 40.0
    return berths


def _make_cranes(n: int, quay_length: float) -> list[QuayCrane]:
    return [
        QuayCrane(
            id=f"QC{i + 1}",
            position_m=round(quay_length * (i + 0.5) / n, 1),
            efficiency=round(random.Random(1000 + i).uniform(28.0, 32.0), 1),
        )
        for i in range(n)
    ]


def _make_blocks(n_import: int, n_export: int, bays: int = 25,
                 stacks_per_bay: int = 8, tiers: int = 5) -> list[ContainerBlock]:
    blocks: list[ContainerBlock] = []
    for i in range(n_import):
        blocks.append(ContainerBlock(
            id=f"YI{i + 1:02d}", block_type="import",
            bays=bays, stacks_per_bay=stacks_per_bay, tiers=tiers))
    for i in range(n_export):
        blocks.append(ContainerBlock(
            id=f"YE{i + 1:02d}", block_type="export",
            bays=bays, stacks_per_bay=stacks_per_bay, tiers=tiers))
    return blocks


def _make_vessels(rng: random.Random, n: int, size_profile: str,
                  berths: list[Berth], eta_span: float, peak_ratio: float,
                  peak_window: tuple[float, float]) -> list[Vessel]:
    weights = SIZE_WEIGHTS[size_profile]
    max_depth = max(b.depth_m for b in berths)
    max_length = max(b.length_m for b in berths)
    vessels: list[Vessel] = []
    for i in range(n):
        size = _weighted_choice(rng, list(zip(VESSEL_SIZE_PARAMS, weights)))
        p = VESSEL_SIZE_PARAMS[size]
        if rng.random() < peak_ratio:
            # 高峰聚簇到港
            lo, hi = peak_window
            eta = rng.uniform(lo, hi)
        else:
            eta = rng.uniform(0.0, eta_span)
        moves = int(rng.uniform(*p["moves"]))
        priority = int(_weighted_choice(rng, PRIORITY_WEIGHTS))
        # 保证静态可行性：吃水/船长不超过最大泊位规格
        draft = round(min(rng.uniform(*p["draft"]), max_depth - 0.3), 1)
        length = round(min(rng.uniform(*p["length"]), max_length - 5.0), 1)
        v = Vessel(
            id=f"V{i + 1:03d}", name=f"MV-Orient-{i + 1:03d}", size=size,
            length_m=length,
            draft_m=draft,
            eta=round(eta, 2), moves=moves, priority=priority,
        )
        # 30% 船舶有合约偏好泊位（从静态可行泊位中选择）
        if rng.random() < 0.3:
            feas = [b for b in berths if b.can_host(v)]
            if feas:
                v = v.model_copy(update={"preferred_berth": rng.choice(feas).id})
        vessels.append(v)
    vessels.sort(key=lambda x: x.eta)
    return vessels


def _make_containers(rng: random.Random, vessels: list[Vessel]) -> list[Container]:
    """按船生成进出口箱明细（seq 为装船/提箱顺序）。"""
    containers: list[Container] = []
    seq_no = 0
    for v in vessels:
        for kind, count in (("import", v.import_moves), ("export", v.export_moves)):
            for s in range(1, count + 1):
                seq_no += 1
                containers.append(Container(
                    id=f"C{seq_no:06d}", vessel_id=v.id, kind=kind,
                    weight_class=rng.choice(WEIGHT_CLASSES),
                    seq=s, destination=rng.choice(DESTINATIONS),
                ))
    return containers


def generate_scenario(
    name: str = "smartport-40v",
    n_vessels: int = 40,
    n_berths: int = 5,
    n_cranes: int = 12,
    n_import_blocks: int = 6,
    n_export_blocks: int = 5,
    size_profile: str = "large_port",
    eta_span_hours: float = 30.0,
    peak_ratio: float = 0.6,
    peak_window: tuple[float, float] = (8.0, 20.0),
    horizon_hours: float = 72.0,
    seed: int = 7,
    block_bays: int = 25,
    block_stacks_per_bay: int = 8,
    block_tiers: int = 5,
) -> Scenario:
    """生成标准算例（默认 40 船 / 5 泊位 / 12 岸桥）。"""
    rng = random.Random(seed)
    berths = _make_berths(n_berths)
    quay_length = sum(b.length_m + 40 for b in berths)
    cranes = _make_cranes(n_cranes, quay_length)
    blocks = _make_blocks(
        n_import_blocks, n_export_blocks,
        bays=block_bays, stacks_per_bay=block_stacks_per_bay,
        tiers=block_tiers)
    vessels = _make_vessels(
        rng, n_vessels, size_profile, berths,
        eta_span_hours, peak_ratio, peak_window)
    containers = _make_containers(rng, vessels)
    return Scenario(
        name=name, horizon_hours=horizon_hours, vessels=vessels,
        berths=berths, cranes=cranes, blocks=blocks, containers=containers,
    )


# ---------------------------------------------------------------- 文献算例
LITERATURE_DIR = Path(__file__).resolve().parents[2] / "configs" / "literature"
LITERATURE_REGISTRY: dict[str, str] = {
    # 自编 8 船算例，格式与公开文献 BAP 算例（如 Imai 系列表格）一致
    "imai-style-8v": "imai_style_8vessels.json",
}


def register_literature_instance(name: str, filename: str) -> None:
    """注册新的文献算例（放置于 configs/literature/ 目录）。"""
    LITERATURE_REGISTRY[name] = filename


def load_literature_instance(name: str) -> Scenario:
    """加载文献算例为 Scenario。

    支持 JSON：{"berths": [...], "vessels": [{id, eta, moves, priority,
    length, draft, preferred?}, ...]}
    """
    if name not in LITERATURE_REGISTRY:
        raise KeyError(
            f"literature instance '{name}' not registered; "
            f"available: {list(LITERATURE_REGISTRY)}")
    path = LITERATURE_DIR / LITERATURE_REGISTRY[name]
    return load_instance_file(path)


def load_instance_file(path: str | Path) -> Scenario:
    """从文献格式文件（JSON/CSV）构建 Scenario。"""
    path = Path(path)
    if path.suffix.lower() == ".json":
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        berths = [Berth.model_validate(b) for b in data.get("berths", [])]
        vessel_rows = data.get("vessels", [])
        crane_count = int(data.get("n_cranes", max(len(berths) * 2, 4)))
    elif path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        berths_spec = path.stem
        berths = _make_berths(3 if "small" in berths_spec else 5)
        vessel_rows = rows
        crane_count = int(rows[0].get("n_cranes", 6)) if rows else 6
    else:
        raise ValueError(f"unsupported instance format: {path.suffix}")

    quay_length = sum(b.length_m + 40 for b in berths) or 800.0
    vessels = [
        Vessel(
            id=str(r["id"]), name=str(r.get("name", r["id"])),
            size=str(r.get("size", "medium")),
            length_m=float(r["length"]), draft_m=float(r["draft"]),
            eta=float(r["eta"]), moves=int(r["moves"]),
            priority=int(r.get("priority", 3)),
            preferred_berth=r.get("preferred") or None,
        )
        for r in vessel_rows
    ]
    rng = random.Random(11)
    containers = _make_containers(rng, vessels)
    n_import = max(len(vessels) // 8, 2)
    n_export = max(len(vessels) // 8, 2)
    return Scenario(
        name=f"literature:{path.stem}", horizon_hours=72.0,
        vessels=vessels, berths=berths,
        cranes=_make_cranes(crane_count, quay_length),
        blocks=_make_blocks(n_import, n_export),
        containers=containers,
    )
