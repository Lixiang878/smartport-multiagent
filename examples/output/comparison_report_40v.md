# SmartPort 调度方案对比报告

- 算例船舶数：40
- 对比模式：FCFS 基准, 遗传算法(NSGA-II), 精确求解(MIP)

## 指标对比
```
--------------------------------------------------------------------
指标                       FCFS 基准     遗传算法(NSGA-II)         精确求解(MIP)
--------------------------------------------------------------------
平均在港时间(h)                  24.43             17.54             27.32
平均等待时间(h)                  19.01             12.20             21.98
等待峰值(h)                    45.75             38.91             53.18
翻箱次数                           0                 0                 0
千箱翻箱率                        0.0               0.0               0.0
岸桥利用率                      53.4%             66.5%             54.6%
泊位利用率                      59.1%             72.6%             59.6%
总完工时刻(h)                   73.25             58.80             71.64
求解耗时(s)                      0.0               4.4              25.7
--------------------------------------------------------------------
```

## 相对 FCFS 基准的改进

| 指标 | 遗传算法(NSGA-II) | 精确求解(MIP) |
|---|---|---|
| 平均在港时间(h) | -28.2% | +11.8% |
| 平均等待时间(h) | -35.8% | +15.6% |
| 等待峰值(h) | -15.0% | +16.2% |
| 翻箱次数 | n/a | n/a |

## 过程记录（仲裁 / 降级）
- [FCFS 基准] [arbitration r1] berth B1: V009 keeps berth, V011 delayed to 23.31h (rule: rule: priority=1 moves=217 wait=7.7h)
- [FCFS 基准] [arbitration r2] berth B2: V038 keeps berth, V040 delayed to 24.11h (rule: rule: priority=3 moves=295 wait=7.5h)
- [FCFS 基准] [arbitration r3] berth B2: V037 keeps berth, V034 delayed to 30.13h (rule: rule: priority=3 moves=149 wait=14.3h)
- [FCFS 基准] [arbitration r4] berth B2: V033 keeps berth, V034 delayed to 39.44h (rule: rule: priority=4 moves=404 wait=18.0h)
- [FCFS 基准] [arbitration r5] berth B2: V001 keeps berth, V033 delayed to 41.53h (rule: rule: priority=3 moves=130 wait=23.1h)
- [FCFS 基准] [arbitration r6] berth B3: V022 keeps berth, V016 delayed to 29.85h (rule: rule: priority=2 moves=232 wait=12.7h)
- [FCFS 基准] [arbitration r7] berth B3: V028 keeps berth, V016 delayed to 38.19h (rule: rule: priority=2 moves=503 wait=15.7h)
- [FCFS 基准] [arbitration r8] berth B4: V023 keeps berth, V017 delayed to 25.05h (rule: rule: priority=3 moves=417 wait=7.3h)
- [FCFS 基准] [arbitration r9] berth B5: V013 keeps berth, V025 delayed to 20.00h (rule: rule: priority=2 moves=608 wait=1.2h)
- [FCFS 基准] [arbitration r10] berth B5: V035 keeps berth, V025 delayed to 30.49h (rule: rule: priority=4 moves=392 wait=12.2h)
- [FCFS 基准] [arbitration r11] berth B5: V026 keeps berth, V025 delayed to 33.95h (rule: rule: priority=1 moves=209 wait=17.0h)
- [FCFS 基准] final review: berth plan consistent
- [遗传算法(NSGA-II)] final review: berth plan consistent
- [精确求解(MIP)] final review: berth plan consistent
