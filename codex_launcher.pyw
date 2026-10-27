"""Windowless Windows entry point; keep startup diagnostics in the pet folder."""
from pathlib import Path
import sys
import traceback

root = Path(__file__).resolve().parent
local = root / ".local"
local.mkdir(exist_ok=True)
with (local / "companion.log").open("a", encoding="utf-8", buffering=1) as log:
    sys.stdout = sys.stderr = log
    try:
        from codex_companion import main
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
    if code:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"桌宠启动或运行失败，请查看：\n{local / 'helper.log'}\n{local / 'companion.log'}",
                                         "Codex 大肥鱼", 0x10)
raise SystemExit(code)
