from smartport.utils.sensitivity import crane_sensitivity


def test_crane_sensitivity_small_sweep():
    rows = crane_sensitivity(n_vessels=8, n_berths=2, cranes_min=3,
                             cranes_max=4, ga_generations=30, seed=7)
    assert len(rows) == 2
    for row in rows:
        assert set(row) == {"n_cranes", "fcfs_total_port_hours",
                            "ga_total_port_hours", "improvement"}
        assert row["fcfs_total_port_hours"] > 0
        assert row["ga_total_port_hours"] > 0
        # GA 不应显著差于 FCFS（同种子下改善幅度可为小负值，但不应崩溃）
        assert row["improvement"] > -0.2
