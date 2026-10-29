from __future__ import annotations

import getpass
import os
import sys


def read_line(prompt: str, *, secret: bool = False) -> str:
    if os.name != "nt" or not sys.stdin.isatty():
        if secret:
            return getpass.getpass(prompt)
        return input(prompt)

    import ctypes
    import msvcrt

    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    kernel32 = ctypes.windll.kernel32
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        if secret:
            return getpass.getpass(prompt)
        return input(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()
    original_mode = mode.value
    line_mode = original_mode | 0x0002 | 0x0001
    if secret:
        line_mode &= ~0x0004
    else:
        line_mode |= 0x0004
    kernel32.SetConsoleMode(handle, line_mode)
    try:
        buffer = ctypes.create_unicode_buffer(4096)
        read = ctypes.c_uint32()
        if not kernel32.ReadConsoleW(handle, buffer, len(buffer) - 1, ctypes.byref(read), None):
            raise OSError("ReadConsoleW failed")
        value = buffer.value[:read.value].rstrip("\r\n")
        sys.stdout.write("\n")
        sys.stdout.flush()
        return value
    finally:
        kernel32.SetConsoleMode(handle, original_mode)
