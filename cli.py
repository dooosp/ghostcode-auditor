#!/usr/bin/env python3
"""GhostCode Auditor CLI — quality-gate 연동용."""

import argparse
import json
import sys
from pathlib import Path

# engine 모듈 import를 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from engine.pipeline import run_full_scan


def main():
    parser = argparse.ArgumentParser(description="GhostCode Auditor CLI")
    parser.add_argument("repo_path", help="스캔할 프로젝트 경로")
    parser.add_argument("--format", choices=["json", "text"], default="json",
                        help="출력 포맷 (default: json)")
    parser.add_argument("--repo-name", default="", help="리포지토리 이름 (생략 시 디렉토리명)")
    args = parser.parse_args()

    repo_path = str(Path(args.repo_path).resolve())
    if not Path(repo_path).is_dir():
        print(json.dumps({"status": "error", "message": f"경로 없음: {repo_path}"}))
        sys.exit(1)

    report = run_full_scan(repo_path, args.repo_name)

    if args.format == "json":
        print(json.dumps(report, default=str, ensure_ascii=False))
    else:
        summary = report.get("summary", {})
        print(f"Scanned: {summary.get('scanned_units', 0)} units")
        print(f"Shadow:  {summary.get('shadow_count', 0)} detected")
        print(f"Status:  {'WARN' if summary.get('shadow_count', 0) > 0 else 'PASS'}")


if __name__ == "__main__":
    main()
