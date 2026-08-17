"""pytest 共享 fixtures：小算例与测试港资源。"""
from __future__ import annotations

import pytest

from smartport.core.models import Berth, QuayCrane
from smartport.utils.instance_gen import generate_scenario


@pytest.fixture(scope="session")
def scenario10() -> object:
    """10 船 / 3 泊位 / 6 岸桥标准小算例。"""
    return generate_scenario(
        name="test-10v", n_vessels=10, n_berths=3, n_cranes=6,
        n_import_blocks=2, n_export_blocks=2, size_profile="small_port",
        eta_span_hours=14.0, peak_ratio=0.7, peak_window=(3.0, 9.0),
        seed=11, block_bays=20, block_stacks_per_bay=6, block_tiers=4,
    )


@pytest.fixture()
def berth_crane_set() -> tuple[list[Berth], list[QuayCrane]]:
    berths = [
        Berth(id="B1", length_m=280, depth_m=12, position_m=0),
        Berth(id="B2", length_m=320, depth_m=13, position_m=320),
    ]
    cranes = [QuayCrane(id=f"QC{i}", position_m=200.0 * i, efficiency=30.0)
              for i in range(1, 5)]
    return berths, cranes
