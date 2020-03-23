from typing import Sequence, Dict
import json

from ml.src.metrics import Metric

Metrics = Dict[str, Sequence[Metric]]


def dump_dict(path, dict_):
    with open(path, 'w') as f:
        json.dump(dict_, f, indent=4)
