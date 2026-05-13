from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


QHYCCD_SUCCESS = 0
QHYCCD_ERROR = 0xFFFFFFFF
SINGLE_MODE = 0
CONTROL_EXPOSURE = 8
MAX_SAFE_FRAME_BYTES = 512 * 1024 * 1024


class QHYCCDError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChipInfo:
    chip_width_mm: float
    chip_height_mm: float
    image_width: int
    image_height: int
    pixel_width_um: float
    pixel_height_um: float
    bpp: int


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    bpp: int
    channels: int
    data: bytes


def _candidate_library_paths() -> list[Path | str]:
    candidates: list[Path | str] = []

    env_dll = os.getenv("QHYCCD_DLL")
    if env_dll:
        candidates.append(Path(env_dll))

    env_dir = os.getenv("QHYCCD_SDK_DIR")
    if env_dir:
        sdk_dir = Path(env_dir)
        candidates.extend(
            [
                sdk_dir / "qhyccd.dll",
                sdk_dir / "libqhyccd.dll",
                sdk_dir / "lib" / "qhyccd.dll",
                sdk_dir / "lib" / "libqhyccd.dll",
                sdk_dir / "bin" / "qhyccd.dll",
                sdk_dir / "bin" / "libqhyccd.dll",
            ]
        )

    here = Path(__file__).resolve().parent
    candidates.extend(
        [
            here / "qhyccd.dll",
            here / "libqhyccd.dll",
            here / "lib" / "qhyccd.dll",
            here / "lib" / "libqhyccd.dll",
        ]
    )

    found = ctypes.util.find_library("qhyccd")
    if found:
        candidates.append(found)

    if sys.platform.startswith("win"):
        candidates.append("qhyccd.dll")
    else:
        candidates.extend(["libqhyccd.so", "libqhyccd.dylib"])

    return candidates


def _load_library() -> ctypes.CDLL:
    errors: list[str] = []

    for candidate in _candidate_library_paths():
        try:
            if isinstance(candidate, Path):
                if not candidate.exists():
                    continue
                if sys.platform.startswith("win"):
                    os.add_dll_directory(str(candidate.parent))
                return ctypes.WinDLL(str(candidate)) if sys.platform.startswith("win") else ctypes.CDLL(str(candidate))

            return ctypes.WinDLL(candidate) if sys.platform.startswith("win") else ctypes.CDLL(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    hint = (
        "未能加载 QHYCCD SDK 动态库。请将 qhyccd.dll 放到程序目录/lib 目录，"
        "或设置环境变量 QHYCCD_DLL 指向 dll 完整路径。"
    )
    if errors:
        hint += "\n尝试过的路径：\n" + "\n".join(errors)
    raise QHYCCDError(hint)


def _check_return(code: int, action: str) -> None:
    if code != QHYCCD_SUCCESS:
        raise QHYCCDError(f"{action} 失败，返回值: 0x{code:08X}")


class QHYCCD:
    def __init__(self) -> None:
        self.lib = _load_library()
        self._bind_functions()
        self.handle: ctypes.c_void_p | None = None
        self.chip_info: ChipInfo | None = None
        self.frame_buffer: ctypes.Array[ctypes.c_uint8] | None = None

    def _bind_functions(self) -> None:
        c_void_p = ctypes.c_void_p
        c_uint32_p = ctypes.POINTER(ctypes.c_uint32)

        self.lib.InitQHYCCDResource.argtypes = []
        self.lib.InitQHYCCDResource.restype = ctypes.c_uint32

        self.lib.ReleaseQHYCCDResource.argtypes = []
        self.lib.ReleaseQHYCCDResource.restype = ctypes.c_uint32

        self.lib.EnableQHYCCDMessage.argtypes = [ctypes.c_bool]
        self.lib.EnableQHYCCDMessage.restype = None

        self.lib.ScanQHYCCD.argtypes = []
        self.lib.ScanQHYCCD.restype = ctypes.c_uint32

        self.lib.GetQHYCCDId.argtypes = [ctypes.c_uint32, ctypes.c_char_p]
        self.lib.GetQHYCCDId.restype = ctypes.c_uint32

        self.lib.OpenQHYCCD.argtypes = [ctypes.c_char_p]
        self.lib.OpenQHYCCD.restype = c_void_p

        self.lib.CloseQHYCCD.argtypes = [c_void_p]
        self.lib.CloseQHYCCD.restype = ctypes.c_uint32

        self.lib.SetQHYCCDReadMode.argtypes = [c_void_p, ctypes.c_uint32]
        self.lib.SetQHYCCDReadMode.restype = ctypes.c_uint32

        self.lib.SetQHYCCDStreamMode.argtypes = [c_void_p, ctypes.c_uint8]
        self.lib.SetQHYCCDStreamMode.restype = ctypes.c_uint32

        self.lib.InitQHYCCD.argtypes = [c_void_p]
        self.lib.InitQHYCCD.restype = ctypes.c_uint32

        self.lib.SetQHYCCDBitsMode.argtypes = [c_void_p, ctypes.c_uint32]
        self.lib.SetQHYCCDBitsMode.restype = ctypes.c_uint32

        self.lib.GetQHYCCDChipInfo.argtypes = [
            c_void_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            c_uint32_p,
            c_uint32_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            c_uint32_p,
        ]
        self.lib.GetQHYCCDChipInfo.restype = ctypes.c_uint32

        self.lib.SetQHYCCDResolution.argtypes = [
            c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        self.lib.SetQHYCCDResolution.restype = ctypes.c_uint32

        self.lib.SetQHYCCDParam.argtypes = [c_void_p, ctypes.c_int, ctypes.c_double]
        self.lib.SetQHYCCDParam.restype = ctypes.c_uint32

        self.lib.GetQHYCCDMemLength.argtypes = [c_void_p]
        self.lib.GetQHYCCDMemLength.restype = ctypes.c_uint32

        self.lib.ExpQHYCCDSingleFrame.argtypes = [c_void_p]
        self.lib.ExpQHYCCDSingleFrame.restype = ctypes.c_uint32

        self.lib.GetQHYCCDSingleFrame.argtypes = [
            c_void_p,
            c_uint32_p,
            c_uint32_p,
            c_uint32_p,
            c_uint32_p,
            ctypes.POINTER(ctypes.c_uint8),
        ]
        self.lib.GetQHYCCDSingleFrame.restype = ctypes.c_uint32

    def connect_first_camera(self, exposure_us: float) -> ChipInfo:
        if self.handle:
            self.set_exposure(exposure_us)
            assert self.chip_info is not None
            return self.chip_info

        _check_return(self.lib.InitQHYCCDResource(), "InitQHYCCDResource")
        self.lib.EnableQHYCCDMessage(True)

        camera_count = self.lib.ScanQHYCCD()
        if camera_count == 0 or camera_count == QHYCCD_ERROR:
            raise QHYCCDError("未发现相机")

        camera_id = ctypes.create_string_buffer(32)
        _check_return(self.lib.GetQHYCCDId(0, camera_id), "GetQHYCCDId")

        handle = self.lib.OpenQHYCCD(camera_id)
        if not handle:
            raise QHYCCDError("OpenQHYCCD 失败")
        self.handle = ctypes.c_void_p(handle)

        try:
            _check_return(self.lib.SetQHYCCDReadMode(self.handle, 0), "SetQHYCCDReadMode")
            _check_return(self.lib.SetQHYCCDStreamMode(self.handle, SINGLE_MODE), "SetQHYCCDStreamMode")
            _check_return(self.lib.InitQHYCCD(self.handle), "InitQHYCCD")
            _check_return(self.lib.SetQHYCCDBitsMode(self.handle, 16), "SetQHYCCDBitsMode(16)")

            chip_info = self._read_chip_info()
            _check_return(
                self.lib.SetQHYCCDResolution(self.handle, 0, 0, chip_info.image_width, chip_info.image_height),
                "SetQHYCCDResolution",
            )
            self.set_exposure(exposure_us)
            self._allocate_frame_buffer(chip_info)
            self.chip_info = chip_info
            return chip_info
        except Exception:
            self.close()
            raise

    def _read_chip_info(self) -> ChipInfo:
        chip_w = ctypes.c_double()
        chip_h = ctypes.c_double()
        image_w = ctypes.c_uint32()
        image_h = ctypes.c_uint32()
        pixel_w = ctypes.c_double()
        pixel_h = ctypes.c_double()
        bpp = ctypes.c_uint32()

        _check_return(
            self.lib.GetQHYCCDChipInfo(
                self.handle,
                ctypes.byref(chip_w),
                ctypes.byref(chip_h),
                ctypes.byref(image_w),
                ctypes.byref(image_h),
                ctypes.byref(pixel_w),
                ctypes.byref(pixel_h),
                ctypes.byref(bpp),
            ),
            "GetQHYCCDChipInfo",
        )

        return ChipInfo(
            chip_width_mm=chip_w.value,
            chip_height_mm=chip_h.value,
            image_width=image_w.value,
            image_height=image_h.value,
            pixel_width_um=pixel_w.value,
            pixel_height_um=pixel_h.value,
            bpp=bpp.value,
        )

    def _allocate_frame_buffer(self, chip_info: ChipInfo) -> None:
        assert self.handle is not None
        mem_len = self.lib.GetQHYCCDMemLength(self.handle)
        if mem_len == 0 or mem_len == QHYCCD_ERROR:
            raise QHYCCDError(f"GetQHYCCDMemLength 返回无效值: 0x{mem_len:08X}")

        expected_len = chip_info.image_width * chip_info.image_height * chip_info.bpp // 8
        if mem_len < expected_len:
            raise QHYCCDError(f"GetQHYCCDMemLength 太小: {mem_len}, 期望至少 {expected_len}")
        if mem_len > MAX_SAFE_FRAME_BYTES:
            raise QHYCCDError(f"GetQHYCCDMemLength 异常偏大: {mem_len} bytes")

        self.frame_buffer = (ctypes.c_uint8 * mem_len)()

    def set_exposure(self, exposure_us: float) -> None:
        if not self.handle:
            raise QHYCCDError("相机未连接")
        _check_return(
            self.lib.SetQHYCCDParam(self.handle, CONTROL_EXPOSURE, float(exposure_us)),
            "SetQHYCCDParam(CONTROL_EXPOSURE)",
        )

    def capture_single_frame(self, exposure_us: float) -> Frame:
        if not self.handle or self.frame_buffer is None or self.chip_info is None:
            self.connect_first_camera(exposure_us)

        assert self.handle is not None
        assert self.frame_buffer is not None
        assert self.chip_info is not None

        self.set_exposure(exposure_us)
        _check_return(self.lib.ExpQHYCCDSingleFrame(self.handle), "ExpQHYCCDSingleFrame")
        time.sleep(0.3)

        width = ctypes.c_uint32(self.chip_info.image_width)
        height = ctypes.c_uint32(self.chip_info.image_height)
        bpp = ctypes.c_uint32(self.chip_info.bpp)
        channels = ctypes.c_uint32(1)

        code = self.lib.GetQHYCCDSingleFrame(
            self.handle,
            ctypes.byref(width),
            ctypes.byref(height),
            ctypes.byref(bpp),
            ctypes.byref(channels),
            self.frame_buffer,
        )
        _check_return(code, "GetQHYCCDSingleFrame")

        byte_len = width.value * height.value * channels.value * max(bpp.value, 8) // 8
        return Frame(
            width=width.value,
            height=height.value,
            bpp=bpp.value,
            channels=channels.value,
            data=bytes(self.frame_buffer[:byte_len]),
        )

    def close(self) -> None:
        if self.handle:
            self.lib.CloseQHYCCD(self.handle)
            self.handle = None
        try:
            self.lib.ReleaseQHYCCDResource()
        except Exception:
            pass

    def __enter__(self) -> QHYCCD:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
