from __future__ import annotations

import ctypes
import logging
import os
import re
from collections import defaultdict
from ctypes import wintypes
from typing import Iterable


LOGGER = logging.getLogger(__name__)
PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
ERROR_SUCCESS = 0

_INSTANCE_RE = re.compile(
    r"luid_(?P<luid>0x[0-9a-f]+_0x[0-9a-f]+)_phys_(?P<phys>\d+)_eng_(?P<eng>\d+)",
    re.IGNORECASE,
)


def aggregate_engine_values(
    values: Iterable[tuple[str, float]], preferred_physical_index: int = 0
) -> float | None:
    """Aggregate per-process counters the same way Task Manager presents engines.

    Values for the same physical engine are summed and capped at 100; the busiest
    engine is used as the adapter utilization.
    """
    grouped: dict[tuple[str, int, int], float] = defaultdict(float)
    for instance, raw_value in values:
        match = _INSTANCE_RE.search(instance)
        if not match or int(match.group("phys")) != preferred_physical_index:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if value < 0 or value != value:  # negative or NaN
            continue
        key = (
            match.group("luid").casefold(),
            int(match.group("phys")),
            int(match.group("eng")),
        )
        grouped[key] += value
    if not grouped:
        return None
    return max(min(100.0, total) for total in grouped.values())


if os.name == "nt":
    class _ValueUnion(ctypes.Union):
        _fields_ = [
            ("longValue", wintypes.LONG),
            ("doubleValue", ctypes.c_double),
            ("largeValue", ctypes.c_longlong),
            ("AnsiStringValue", ctypes.c_char_p),
            ("WideStringValue", wintypes.LPWSTR),
        ]


    class _FmtCounterValue(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("CStatus", wintypes.DWORD), ("value", _ValueUnion)]


    class _FmtCounterValueItem(ctypes.Structure):
        _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtCounterValue)]


class GpuSampler:
    COUNTER_PATH = r"\GPU Engine(*)\Utilization Percentage"

    def __init__(self, preferred_physical_index: int = 0):
        self.preferred_physical_index = preferred_physical_index
        self.available = False
        self.error: str | None = None
        self._query = wintypes.HANDLE() if os.name == "nt" else None
        self._counter = wintypes.HANDLE() if os.name == "nt" else None
        if os.name == "nt":
            self._initialize()
        else:
            self.error = "Windows以外ではGPU Engineカウンターを利用できません。"

    @staticmethod
    def _code(status: int) -> int:
        return int(status) & 0xFFFFFFFF

    def _initialize(self) -> None:
        try:
            self._pdh = ctypes.WinDLL("pdh.dll")
            self._pdh.PdhOpenQueryW.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_size_t,
                ctypes.POINTER(wintypes.HANDLE),
            ]
            self._pdh.PdhOpenQueryW.restype = wintypes.LONG
            self._pdh.PdhAddEnglishCounterW.argtypes = [
                wintypes.HANDLE,
                wintypes.LPCWSTR,
                ctypes.c_size_t,
                ctypes.POINTER(wintypes.HANDLE),
            ]
            self._pdh.PdhAddEnglishCounterW.restype = wintypes.LONG
            self._pdh.PdhCollectQueryData.argtypes = [wintypes.HANDLE]
            self._pdh.PdhCollectQueryData.restype = wintypes.LONG
            self._pdh.PdhGetFormattedCounterArrayW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ]
            self._pdh.PdhGetFormattedCounterArrayW.restype = wintypes.LONG
            self._pdh.PdhCloseQuery.argtypes = [wintypes.HANDLE]
            self._pdh.PdhCloseQuery.restype = wintypes.LONG

            status = self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query))
            if self._code(status) != ERROR_SUCCESS:
                raise OSError(f"PdhOpenQueryW: 0x{self._code(status):08X}")
            status = self._pdh.PdhAddEnglishCounterW(
                self._query, self.COUNTER_PATH, 0, ctypes.byref(self._counter)
            )
            if self._code(status) != ERROR_SUCCESS:
                raise OSError(f"PdhAddEnglishCounterW: 0x{self._code(status):08X}")
            status = self._pdh.PdhCollectQueryData(self._query)
            if self._code(status) != ERROR_SUCCESS:
                raise OSError(f"PdhCollectQueryData: 0x{self._code(status):08X}")
            self.available = True
        except Exception as exc:  # PDH availability differs across Windows builds.
            self.error = str(exc)
            LOGGER.warning("GPUカウンターを初期化できません: %s", exc)
            self.close()

    def sample(self) -> float | None:
        if not self.available:
            return None
        status = self._pdh.PdhCollectQueryData(self._query)
        if self._code(status) != ERROR_SUCCESS:
            self.error = f"PdhCollectQueryData: 0x{self._code(status):08X}"
            return None

        buffer_size = wintypes.DWORD(0)
        item_count = wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            self._counter,
            PDH_FMT_DOUBLE,
            ctypes.byref(buffer_size),
            ctypes.byref(item_count),
            None,
        )
        if self._code(status) not in {PDH_MORE_DATA, ERROR_SUCCESS}:
            self.error = f"PdhGetFormattedCounterArrayW: 0x{self._code(status):08X}"
            return None
        if buffer_size.value == 0 or item_count.value == 0:
            return None

        buffer = ctypes.create_string_buffer(buffer_size.value)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            self._counter,
            PDH_FMT_DOUBLE,
            ctypes.byref(buffer_size),
            ctypes.byref(item_count),
            buffer,
        )
        if self._code(status) != ERROR_SUCCESS:
            self.error = f"PdhGetFormattedCounterArrayW: 0x{self._code(status):08X}"
            return None

        items = ctypes.cast(buffer, ctypes.POINTER(_FmtCounterValueItem))
        values: list[tuple[str, float]] = []
        for index in range(item_count.value):
            item = items[index]
            if item.szName and item.FmtValue.CStatus == ERROR_SUCCESS:
                values.append((item.szName, item.FmtValue.doubleValue))
        return aggregate_engine_values(values, self.preferred_physical_index)

    def close(self) -> None:
        if os.name == "nt" and getattr(self, "_query", None) and self._query.value:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except Exception:
                pass
            self._query = wintypes.HANDLE()
        self.available = False

    def __enter__(self) -> "GpuSampler":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
