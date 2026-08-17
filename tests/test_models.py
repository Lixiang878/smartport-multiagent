"""数据模型测试：字段校验、约束检查、序列化。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from smartport.core.models import (
    Berth,
    BerthAssignment,
    KPI,
    QuayCrane,
    Schedule,
    Vessel,
)


def make_vessel(**kw) -> Vessel:
    base = dict(id="V001", length_m=200, draft_m=10, eta=1.0,
                moves=500, priority=2)
    base.update(kw)
    return Vessel(**base)


class TestVessel:
    def test_default_moves_split(self):
        v = make_vessel()
        assert v.import_moves + v.export_moves == v.moves
        assert v.import_moves == int(v.moves * 0.4)

    def test_explicit_split_kept(self):
        v = make_vessel(import_moves=100, export_moves=200, moves=300)
        assert (v.import_moves, v.export_moves) == (100, 200)

    def test_split_exceeds_total_raises(self):
        with pytest.raises(ValidationError):
            make_vessel(import_moves=400, export_moves=200, moves=500)

    def test_priority_range(self):
        with pytest.raises(ValidationError):
            make_vessel(priority=0)
        with pytest.raises(ValidationError):
            make_vessel(priority=6)

    def test_priority_weight_mapping(self):
        assert make_vessel(priority=1).weight == 5.0
        assert make_vessel(priority=5).weight == 1.0


class TestBerth:
    def test_can_host(self):
        b = Berth(id="B1", length_m=300, depth_m=13)
        assert b.can_host(make_vessel(length_m=280, draft_m=12))
        assert not b.can_host(make_vessel(length_m=320))    # 超长
        assert not b.can_host(make_vessel(draft_m=14))      # 吃水超


class TestSchedule:
    def test_json_round_trip(self, tmp_path):
        plan = [BerthAssignment(vessel_id="V001", berth_id="B1",
                                start=1.0, end=5.0, planned_end=5.0,
                                wait_hours=0.5, service_hours=4.0)]
        sch = Schedule(mode="ga", berth_plan=plan,
                       kpi=KPI(n_vessels=1, avg_port_time_hours=4.5),
                       notes=["test note"])
        path = sch.save(tmp_path / "s.json")
        loaded = Schedule.load(path)
        assert loaded == sch

    def test_port_time_property(self):
        a = BerthAssignment(vessel_id="V1", berth_id="B1", start=3.0,
                            end=8.0, planned_end=8.0,
                            wait_hours=1.5, service_hours=5.0)
        assert a.port_time == 6.5


def test_crane_model():
    qc = QuayCrane(id="QC1")
    assert qc.efficiency == 30.0 and qc.status == "idle"
