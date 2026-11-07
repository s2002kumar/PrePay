"""Compare two development reports: exact equality of every value except the new `stages`."""

import json
import math
import sys

a = json.load(open(sys.argv[1], encoding="utf-8"))
b = json.load(open(sys.argv[2], encoding="utf-8"))
a.pop("stages", None)
stages = b.pop("stages", None)
diffs, worst, count = [], 0.0, 0


def walk(x, y, path):
    global worst, count
    if isinstance(x, dict) and isinstance(y, dict):
        if set(x) != set(y):
            diffs.append((path, "keys", sorted(set(x) ^ set(y))))
        for k in set(x) & set(y):
            walk(x[k], y[k], f"{path}/{k}")
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            diffs.append((path, "len", (len(x), len(y))))
        for i, (u, v) in enumerate(zip(x, y)):
            walk(u, v, f"{path}[{i}]")
    elif isinstance(x, float) and isinstance(y, float):
        count += 1
        if x != y and not (math.isnan(x) and math.isnan(y)):
            rel = abs(x - y) / max(abs(x), abs(y), 1e-300)
            worst = max(worst, rel)
            diffs.append((path, x, y))
    else:
        count += 1
        if x != y:
            diffs.append((path, x, y))


walk(a, b, "")
print(
    json.dumps(
        {
            "values_compared": count,
            "differing_values": len(diffs),
            "max_relative_difference": worst,
            "examples": diffs[:8],
            "new_stages": stages,
        },
        indent=1,
        default=str,
    )
)
