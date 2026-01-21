"""
测试循环辅助脚本

用于解析测试结果、更新检查点、生成报告等。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

REPORT_DIR = Path("tests/report")
CHECKPOINT_FILE = REPORT_DIR / "checkpoint.json"
TEST_RESULTS_FILE = REPORT_DIR / "test_results.json"
BUGLIST_FILE = REPORT_DIR / "buglist.md"
JUNIT_FILE = REPORT_DIR / "junit.xml"


def ensure_report_dir():
    """确保报告目录存在"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_checkpoint() -> Dict[str, Any]:
    """加载检查点文件"""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": "1.0",
        "iteration": 0,
        "max_iterations": 5,
        "phase": "init",
        "started_at": None,
        "last_updated": None,
        "status": "ready",
        "test_summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0},
        "failed_tests": [],
        "fixed_bugs": [],
        "unresolved_issues": [],
        "history": [],
    }


def save_checkpoint(checkpoint: Dict[str, Any]):
    """保存检查点文件"""
    checkpoint["last_updated"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def parse_junit_xml() -> Dict[str, Any]:
    """解析JUnit XML测试报告"""
    if not JUNIT_FILE.exists():
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "failed_tests": []}

    tree = ET.parse(JUNIT_FILE)
    root = tree.getroot()

    # 查找 testsuite 元素
    testsuite = root.find(".//testsuite")
    if testsuite is None:
        testsuite = root

    tests = int(testsuite.get("tests", 0))
    failures = int(testsuite.get("failures", 0))
    errors = int(testsuite.get("errors", 0))
    skipped = int(testsuite.get("skipped", 0))
    passed = tests - failures - errors - skipped

    # 获取失败的测试
    failed_tests = []
    for testcase in root.findall(".//testcase"):
        failure = testcase.find("failure")
        error = testcase.find("error")
        if failure is not None or error is not None:
            classname = testcase.get("classname", "")
            name = testcase.get("name", "")
            message = ""
            if failure is not None:
                message = failure.get("message", "")
            elif error is not None:
                message = error.get("message", "")
            failed_tests.append(
                {"classname": classname, "name": name, "message": message}
            )

    return {
        "total": tests,
        "passed": passed,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "failed_tests": failed_tests,
    }


def update_test_results():
    """更新测试结果JSON文件"""
    ensure_report_dir()
    results = parse_junit_xml()
    results["updated_at"] = datetime.now().isoformat()

    with open(TEST_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


def update_phase(phase: str, status: str = "running", **kwargs):
    """更新检查点阶段"""
    checkpoint = load_checkpoint()

    if checkpoint["started_at"] is None:
        checkpoint["started_at"] = datetime.now().isoformat()

    checkpoint["phase"] = phase
    checkpoint["status"] = status

    # 更新其他字段
    for key, value in kwargs.items():
        checkpoint[key] = value

    # 记录历史
    checkpoint["history"].append(
        {"phase": phase, "status": status, "timestamp": datetime.now().isoformat()}
    )

    save_checkpoint(checkpoint)
    return checkpoint


def increment_iteration():
    """增加迭代次数"""
    checkpoint = load_checkpoint()
    checkpoint["iteration"] += 1
    save_checkpoint(checkpoint)
    return checkpoint["iteration"]


def should_continue() -> bool:
    """检查是否应该继续迭代"""
    checkpoint = load_checkpoint()
    results = (
        json.loads(TEST_RESULTS_FILE.read_text(encoding="utf-8"))
        if TEST_RESULTS_FILE.exists()
        else {"failed": 0}
    )

    # 检查最大迭代
    if checkpoint["iteration"] >= checkpoint["max_iterations"]:
        return False

    # 检查是否还有失败的测试
    if results.get("failed", 0) == 0:
        return False

    return True


def generate_final_summary():
    """生成最终总结报告"""
    checkpoint = load_checkpoint()
    results = (
        json.loads(TEST_RESULTS_FILE.read_text(encoding="utf-8"))
        if TEST_RESULTS_FILE.exists()
        else {}
    )

    status = "✅ 全部通过" if results.get("failed", 0) == 0 else "⚠️ 部分问题未解决"

    summary = f"""# 测试循环最终总结

## 执行概要
- **开始时间**: {checkpoint.get('started_at', 'N/A')}
- **结束时间**: {datetime.now().isoformat()}
- **总迭代次数**: {checkpoint.get('iteration', 0)}
- **最终状态**: {status}

## 测试统计
- 总测试数: {results.get('total', 0)}
- 通过: {results.get('passed', 0)}
- 失败: {results.get('failed', 0)}
- 错误: {results.get('errors', 0)}

## 修复的Bug
{chr(10).join(['- ' + bug for bug in checkpoint.get('fixed_bugs', [])]) or '无'}

## 未解决的问题
{chr(10).join(['- ' + issue for issue in checkpoint.get('unresolved_issues', [])]) or '无'}

## 执行历史
| 阶段 | 状态 | 时间 |
|------|------|------|
"""
    for h in checkpoint.get("history", []):
        summary += f"| {h.get('phase', '')} | {h.get('status', '')} | {h.get('timestamp', '')} |\n"

    summary += """
## 报告文件
- HTML测试报告: tests/report/test_report.html
- 覆盖率报告: tests/report/coverage_html/index.html
- JUnit报告: tests/report/junit.xml
- Bug列表: tests/report/buglist.md
"""

    final_summary_file = REPORT_DIR / "final_summary.md"
    final_summary_file.write_text(summary, encoding="utf-8")
    return summary


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python test_cycle_helper.py <命令>")
        print("命令:")
        print("  init          - 初始化检查点")
        print("  parse         - 解析JUnit XML并更新test_results.json")
        print("  phase <名称>  - 更新当前阶段")
        print("  next          - 增加迭代次数")
        print("  check         - 检查是否应继续")
        print("  summary       - 生成最终总结")
        print("  status        - 显示当前状态")
        return

    cmd = sys.argv[1]

    if cmd == "init":
        ensure_report_dir()
        save_checkpoint(load_checkpoint())
        print("检查点已初始化")

    elif cmd == "parse":
        results = update_test_results()
        print(f"测试结果: {results['passed']}/{results['total']} 通过")
        if results["failed"] > 0:
            print(f"失败: {results['failed']}")

    elif cmd == "phase":
        if len(sys.argv) < 3:
            print("请指定阶段名称")
            return
        phase = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) > 3 else "running"
        update_phase(phase, status)
        print(f"阶段已更新: {phase} ({status})")

    elif cmd == "next":
        iteration = increment_iteration()
        print(f"迭代次数: {iteration}")

    elif cmd == "check":
        if should_continue():
            print("continue")
            sys.exit(0)
        else:
            print("stop")
            sys.exit(1)

    elif cmd == "summary":
        summary = generate_final_summary()
        print("最终总结已生成")

    elif cmd == "status":
        checkpoint = load_checkpoint()
        print(f"迭代: {checkpoint['iteration']}/{checkpoint['max_iterations']}")
        print(f"阶段: {checkpoint['phase']}")
        print(f"状态: {checkpoint['status']}")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
