"""
数据层状态检查工具

用法:
    python tools/check_data_layers.py           # 打印状态报告
    python tools/check_data_layers.py --json    # 输出 JSON 格式
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_config
from src.data_layer.layer_manager import DataLayerManager, check_data_layers


def main():
    parser = argparse.ArgumentParser(description="数据层状态检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    cfg = load_config()
    mgr = DataLayerManager(cfg)

    if args.json:
        status = mgr.check_all_layers()
        output = {}
        for layer_name, s in status.items():
            output[layer_name] = {
                "output_exists": s.output_exists,
                "fingerprint_exists": s.fingerprint_exists,
                "upstream_changed": s.upstream_changed,
                "config_changed": s.config_changed,
                "needs_update": s.needs_update,
                "reason": s.reason,
            }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        mgr.print_status_report()


if __name__ == "__main__":
    main()
