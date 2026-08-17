# 文献算例接口（Literature Instances）

本目录用于放置从公开文献转录的 BAP（泊位分配）算例，供学术对比实验。

## 支持格式

### JSON（推荐）

```json
{
  "n_cranes": 6,
  "berths": [
    {"id": "B1", "length_m": 280, "depth_m": 12, "position_m": 0}
  ],
  "vessels": [
    {"id": "V1", "eta": 0.0, "moves": 320, "priority": 2,
     "length": 210, "draft": 10.5, "preferred": "B1"}
  ]
}
```

字段说明：`length`/`draft` 为船长(m)/吃水(m)；`preferred` 可选（偏好泊位）。

### CSV

列：`id,eta,moves,priority,length,draft,preferred[,n_cranes]`

## 使用方式

```python
from smartport.utils.instance_gen import (
    load_literature_instance, register_literature_instance)

# 加载内置注册的算例
scenario = load_literature_instance("imai-style-8v")

# 注册并加载自己的文献算例
register_literature_instance("akakiya-1995", "akakiya_1995.csv")
scenario = load_literature_instance("akakiya-1995")
```

## 内置算例

| 名称 | 文件 | 说明 |
|------|------|------|
| `imai-style-8v` | `imai_style_8vessels.json` | 8 船/3 泊位小算例，字段结构模拟公开文献 BAP 表格（数据为自编演示数据） |
