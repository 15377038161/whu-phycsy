from __future__ import annotations

import math


ALLOWED_TEMPLATES = {"linear", "polynomial", "exponential", "sine", "rabi", "odmr", "echo"}


def validate_fit_result(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("拟合结果必须是对象")
    code = str(value.get("code", ""))
    if len(code) > 50_000:
        raise ValueError("代码超过 50000 字符")
    params = value.get("final_parameters", {})
    initial = value.get("initial_parameters", {})
    if not isinstance(params, dict) or not isinstance(initial, dict) or len(params) > 100:
        raise ValueError("参数结构无效")
    for group in (params, initial):
        for key, item in group.items():
            if len(str(key)) > 80 or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
                raise ValueError("参数必须是有限数值")
    metrics = value.get("metrics", {})
    if not isinstance(metrics, dict) or len(metrics) > 30:
        raise ValueError("拟合指标结构无效")
    plot = str(value.get("plot_data_url", ""))
    if plot and (not plot.startswith("data:image/png;base64,") or len(plot) > 5_000_000):
        raise ValueError("拟合图像格式或大小无效")
    return {"code": code, "formula": str(value.get("formula", ""))[:500], "initial_parameters": initial, "final_parameters": params, "metrics": metrics, "plot_data_url": plot}
