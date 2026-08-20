import pytest

from smartport.utils.benchmarks import BENCHMARK_NAMES, benchmark_scenario


@pytest.mark.parametrize("name,n_vessels,n_berths,n_cranes", [
    ("imai_5_2", 5, 2, 4),
    ("imai_10_3", 10, 3, 6),
    ("dense_20_5", 20, 5, 8),
])
def test_benchmark_shapes(name, n_vessels, n_berths, n_cranes):
    sc = benchmark_scenario(name)
    assert len(sc.vessels) == n_vessels
    assert len(sc.berths) == n_berths
    assert len(sc.cranes) == n_cranes
    # 到港时刻与长度均为正且确定
    assert all(v.eta >= 0 and v.length_m > 0 for v in sc.vessels)


def test_benchmark_moves_mapping():
    # base_handling 12h × 2 台 × 30 moves/h = 720
    sc = benchmark_scenario("imai_5_2")
    assert sc.vessels[0].moves == 720


def test_unknown_benchmark_raises():
    with pytest.raises(ValueError):
        benchmark_scenario("not_a_benchmark")


def test_benchmark_names_constant():
    assert set(BENCHMARK_NAMES) == {"imai_5_2", "imai_10_3", "dense_20_5"}
