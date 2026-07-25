import sys
from typing import Any, Dict


def run_searcher(searcher: Any) -> bool:
    return bool(searcher.run())


def print_final_message(success: bool) -> None:
    if success:
        print("\n[+] 搜索完成")
    else:
        print("\n[-] 搜索失败")


def exit_code(success: bool) -> int:
    return 0 if success else 1


def os_exit(success: bool) -> None:
    sys.exit(exit_code(success))

