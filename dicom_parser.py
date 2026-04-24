"""
DICOM file parser.
Produces a tree-node list, raw bytes, pixel array, FPS, and WW/WL values.

MPEG2 / MPEG4 / HEVC transfer syntaxes are decoded via imageio-ffmpeg.
"""

import os
import tempfile

# pydicom은 parse_dicom() 호출 시 lazy import (앱 시작 속도 개선)
pydicom = None
MultiValue = None


def _ensure_pydicom():
    global pydicom, MultiValue
    if pydicom is None:
        import pydicom as _pd
        from pydicom.multival import MultiValue as _MV
        pydicom = _pd
        MultiValue = _MV

# VRs that use a 4-byte length field in explicit VR (instead of 2-byte)
_LONG_VRS = frozenset({'OB', 'OD', 'OF', 'OL', 'OW', 'SQ', 'UC', 'UN', 'UR', 'UT'})

# Transfer syntax UIDs that contain a video bitstream (MPEG2 / MPEG4 / HEVC)
_VIDEO_TRANSFER_SYNTAXES = frozenset({
    '1.2.840.10008.1.2.4.100',   # MPEG2 MP/ML
    '1.2.840.10008.1.2.4.101',   # MPEG2 MP/HL
    '1.2.840.10008.1.2.4.102',   # MPEG-4 AVC/H.264 High Profile 4.1
    '1.2.840.10008.1.2.4.103',   # MPEG-4 AVC/H.264 BD-compatible
    '1.2.840.10008.1.2.4.104',   # MPEG-4 AVC/H.264 High Profile 4.2 2D
    '1.2.840.10008.1.2.4.105',   # MPEG-4 AVC/H.264 High Profile 4.2 3D
    '1.2.840.10008.1.2.4.106',   # MPEG-4 AVC/H.264 Stereo
    '1.2.840.10008.1.2.4.110',   # HEVC/H.265 Main
    '1.2.840.10008.1.2.4.111',   # HEVC/H.265 Main 10
})


# ---------------------------------------------------------------------------
# Offset collection (top-level elements only)
# ---------------------------------------------------------------------------

def _collect_offsets(filepath: str) -> dict:
    """
    DICOM 파일을 직접 바이너리 파싱하여 top-level 태그의 파일 오프셋을 수집.
    pydicom 내부 API에 의존하지 않으므로 버전 변경에 강건함.
    """
    import struct

    offsets = {}
    try:
        # 전송 구문 확인 (Implicit VR 여부)
        ds_meta = pydicom.dcmread(filepath, stop_before_pixels=True, force=True)
        ts = ''
        if hasattr(ds_meta, 'file_meta') and hasattr(ds_meta.file_meta, 'TransferSyntaxUID'):
            ts = str(ds_meta.file_meta.TransferSyntaxUID)
        from pydicom.uid import ImplicitVRLittleEndian
        is_implicit = (ts == str(ImplicitVRLittleEndian))

        file_size = os.path.getsize(filepath)

        with open(filepath, 'rb') as fp:
            # 128 바이트 프리앰블 + "DICM" 확인
            fp.seek(128)
            magic = fp.read(4)
            pos = 132 if magic == b'DICM' else 0
            fp.seek(pos)

            in_meta = True  # (0002,xxxx) File Meta는 항상 Explicit VR LE

            while pos < file_size - 4:
                elem_start = pos

                raw_tag = fp.read(4)
                if len(raw_tag) < 4:
                    break
                group, elem_num = struct.unpack_from('<HH', raw_tag)
                pos += 4

                # Pixel Data(7FE0,0010) 이후는 중단
                if group > 0x7FE0:
                    break

                # File Meta 영역 종료 감지
                if in_meta and group != 0x0002:
                    in_meta = False

                use_implicit = is_implicit and not in_meta

                if use_implicit:
                    raw_len = fp.read(4)
                    if len(raw_len) < 4:
                        break
                    length = struct.unpack_from('<I', raw_len)[0]
                    pos += 4
                else:
                    vr_raw = fp.read(2)
                    if len(vr_raw) < 2:
                        break
                    vr = vr_raw.decode('latin-1', errors='replace')
                    pos += 2

                    if vr in _LONG_VRS:
                        fp.read(2)   # reserved 2 bytes
                        raw_len = fp.read(4)
                        if len(raw_len) < 4:
                            break
                        length = struct.unpack_from('<I', raw_len)[0]
                        pos += 6
                    else:
                        raw_len = fp.read(2)
                        if len(raw_len) < 2:
                            break
                        length = struct.unpack_from('<H', raw_len)[0]
                        pos += 2

                offsets[pydicom.tag.Tag(group, elem_num)] = elem_start

                # undefined length → 이후 파싱 불가, 중단
                if length == 0xFFFFFFFF:
                    break

                fp.seek(length, 1)
                pos += length

    except Exception:
        pass

    return offsets


# ---------------------------------------------------------------------------
# Length helper  (pydicom 3.x removed DataElement.length)
# ---------------------------------------------------------------------------

def _elem_length(elem) -> int | None:
    if hasattr(elem, 'length') and isinstance(elem.length, int):
        return elem.length
    val = elem.value
    if val is None:
        return 0
    if isinstance(val, (bytes, bytearray)):
        return len(val)
    if hasattr(val, '__len__'):
        return len(val)
    return None


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

def _fmt_value(elem) -> str:
    if elem.VR == 'SQ':
        n = len(elem.value) if elem.value else 0
        return f"Sequence ({n} item{'s' if n != 1 else ''})"

    if elem.tag == (0x7FE0, 0x0010):
        n = _elem_length(elem)
        size_str = f"{n} bytes" if n is not None else "? bytes"
        return f"<Pixel Data — {size_str}>"

    val = elem.value
    if isinstance(val, (bytes, bytearray)):
        snippet = val[:48].hex(' ')
        return snippet + (' ...' if len(val) > 48 else '')
    if isinstance(val, MultiValue):
        return '\\'.join(str(v) for v in val)
    return str(val)


# ---------------------------------------------------------------------------
# Recursive tree builder
# ---------------------------------------------------------------------------

def _build_nodes(ds, offsets: dict | None = None) -> list:
    nodes = []
    for elem in ds:
        group   = elem.tag.group
        element = elem.tag.element
        tag_str = f"({group:04X},{element:04X})"

        offset_str = f"{offsets[elem.tag]:08X}" if offsets and elem.tag in offsets else ''
        length_val = _elem_length(elem)
        length_str = str(length_val) if isinstance(length_val, int) and length_val >= 0 else ''

        children = []
        if elem.VR == 'SQ' and elem.value:
            for i, item in enumerate(elem.value):
                children.append({
                    'tag':      f'Item {i}',
                    'vr':       '',
                    'length':   '',
                    'name':     f'Sequence Item #{i}',
                    'value':    f'{len(item)} tag(s)',
                    'offset':   '',
                    'children': _build_nodes(item),
                })

        nodes.append({
            'tag':      tag_str,
            'vr':       elem.VR or '',
            'length':   length_str,
            'name':     elem.name or '',
            'value':    _fmt_value(elem),
            'offset':   offset_str,
            'children': children,
        })
    return nodes


# ---------------------------------------------------------------------------
# WW / WL / FPS helpers
# ---------------------------------------------------------------------------

def _scalar(val):
    if val is None:
        return None
    if isinstance(val, MultiValue):
        return float(val[0])
    return float(val)


def _get_fps(ds) -> float:
    """
    Try to determine FPS from DICOM tags.
    Priority: CineRate > RecommendedDisplayFrameRate > 1000/FrameTime
    Default: 10 fps
    """
    try:
        if hasattr(ds, 'CineRate') and ds.CineRate:
            return float(ds.CineRate)
    except Exception:
        pass
    try:
        if hasattr(ds, 'RecommendedDisplayFrameRate') and ds.RecommendedDisplayFrameRate:
            return float(ds.RecommendedDisplayFrameRate)
    except Exception:
        pass
    try:
        if hasattr(ds, 'FrameTime') and ds.FrameTime:
            ft = float(ds.FrameTime)
            if ft > 0:
                return 1000.0 / ft
    except Exception:
        pass
    return 10.0


# ---------------------------------------------------------------------------
# YBR color space conversion
# ---------------------------------------------------------------------------

_YBR_PHOTOMETRICS = frozenset({
    'YBR_FULL', 'YBR_FULL_422',
    'YBR_PARTIAL_422', 'YBR_PARTIAL_420',
    'YBR_ICT', 'YBR_RCT',
})


def _ybr_frame_to_rgb(frame) -> 'np.ndarray':
    """BT.601 YCbCr (8-bit) → RGB 변환 (단일 프레임, shape H×W×3)."""
    import numpy as np
    f  = frame.astype(float)
    y  = f[:, :, 0]
    cb = f[:, :, 1] - 128.0
    cr = f[:, :, 2] - 128.0
    r  = np.clip(y + 1.402   * cr,                    0, 255)
    g  = np.clip(y - 0.34414 * cb - 0.71414 * cr,     0, 255)
    b  = np.clip(y + 1.772   * cb,                    0, 255)
    return np.stack([r, g, b], axis=2).astype(np.uint8)


def _convert_ybr_to_rgb(arr, photometric: str):
    """YBR pixel array → RGB. pydicom convert_color_space 우선, 실패 시 수동 변환."""
    import numpy as np
    try:
        from pydicom.pixels import convert_color_space
        return convert_color_space(arr, photometric, 'RGB')
    except Exception:
        pass

    # 수동 BT.601 변환
    if arr.ndim == 3 and arr.shape[2] == 3:
        return _ybr_frame_to_rgb(arr)
    if arr.ndim == 4 and arr.shape[3] == 3:
        return np.stack([_ybr_frame_to_rgb(arr[i]) for i in range(arr.shape[0])])
    return arr


def _decode_via_pil(ds) -> 'np.ndarray':
    """JPEG/JPEG2000 encapsulated pixel data를 PIL로 직접 디코딩 → RGB ndarray."""
    import numpy as np
    import io
    from PIL import Image
    from pydicom.encaps import decode_data_sequence

    frags  = decode_data_sequence(ds.PixelData)
    frames = []
    for frag in frags:
        img = Image.open(io.BytesIO(frag)).convert('RGB')
        frames.append(np.array(img))

    if not frames:
        raise ValueError('PIL 디코딩: 프레임 없음')
    return frames[0] if len(frames) == 1 else np.stack(frames)


def _get_pixel_array(ds):
    """
    pixel_array 획득 + 필요 시 YBR→RGB 변환.
    실패하면 PIL fallback 시도.
    Returns (array_or_None, error_str_or_None)
    """
    pi = getattr(ds, 'PhotometricInterpretation', '').strip()

    try:
        arr = ds.pixel_array
        if pi in _YBR_PHOTOMETRICS:
            arr = _convert_ybr_to_rgb(arr, pi)
        return arr, None
    except Exception as e:
        first_error = str(e)

    # PIL fallback (JPEG encapsulated)
    try:
        arr = _decode_via_pil(ds)
        return arr, None
    except Exception as e2:
        return None, f'{first_error}  |  PIL fallback: {e2}'


# ---------------------------------------------------------------------------
# Lazy video frame reader  (MPEG2 / MPEG4 / HEVC)
# ---------------------------------------------------------------------------

class LazyVideoReader:
    """
    Wraps an imageio ffmpeg reader to expose frames on demand.
    전체 프레임을 RAM에 올리지 않고, __getitem__ 호출 시마다 한 장씩 읽는다.
    임시 파일은 이 객체가 GC될 때 자동 삭제된다.
    """

    def __init__(self, tmp_path: str, num_frames: int, fps: float,
                 height: int, width: int):
        self._path     = tmp_path
        self._fps      = fps
        self.shape     = (num_frames, height, width, 3)
        self.ndim      = 4
        self.dtype     = 'uint8'
        self._reader   = None
        self._last_idx = -2   # 첫 접근 시 강제 open

    def __len__(self) -> int:
        return self.shape[0]

    def __getitem__(self, idx: int):
        import imageio
        import numpy as np
        idx = int(idx)

        # 역방향 이동이거나 reader가 닫혀 있으면 재오픈
        if self._reader is None or idx <= self._last_idx:
            if self._reader is not None:
                try:
                    self._reader.close()
                except Exception:
                    pass
            self._reader = imageio.get_reader(self._path, format='ffmpeg')

        try:
            frame = self._reader.get_data(idx)
        except Exception:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = imageio.get_reader(self._path, format='ffmpeg')
            frame = self._reader.get_data(idx)

        self._last_idx = idx
        return np.asarray(frame)

    def __del__(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
        if os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Video decoder — writes bitstream to temp file, returns LazyVideoReader
# ---------------------------------------------------------------------------

def _decode_video(ds) -> tuple:
    """
    Returns (LazyVideoReader, fps).
    임시 파일은 LazyVideoReader 소멸 시 자동 삭제.
    """
    import imageio

    # 비트스트림 추출
    try:
        from pydicom.encaps import decode_data_sequence
        frags = decode_data_sequence(ds.PixelData)
        video_bytes = b''.join(frags)
    except Exception:
        video_bytes = bytes(ds.PixelData)

    # 전송 구문에 따라 확장자 결정 (ffmpeg 프로브 힌트)
    ts = str(ds.file_meta.TransferSyntaxUID) if hasattr(ds, 'file_meta') else ''
    suffix = '.mpg' if ts in {
        '1.2.840.10008.1.2.4.100',
        '1.2.840.10008.1.2.4.101',
    } else '.mp4'

    # 임시 파일 기록 (LazyVideoReader가 삭제 관리)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(video_bytes)
        tmp_path = f.name

    try:
        reader = imageio.get_reader(tmp_path, format='ffmpeg')
        meta   = reader.get_meta_data()
        fps    = float(meta.get('fps', _get_fps(ds)))
        w, h   = meta['source_size']          # (width, height)

        # 프레임 수: duration × fps 로 추산 (count_frames 는 전체 디코딩으로 느릴 수 있음)
        duration = float(meta.get('duration', 0))
        if duration > 0:
            num_frames = max(1, int(fps * duration))
        else:
            n = reader.count_frames()
            num_frames = n if isinstance(n, int) and 0 < n < 500_000 else 1
        reader.close()

        return LazyVideoReader(tmp_path, num_frames, fps, h, w), fps

    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dicom(filepath: str):
    """
    Returns
    -------
    nodes        : list of tag-tree node dicts (recursive)
    raw_bytes    : bytes — full file content (for hex dump)
    pixel_array  : numpy ndarray or None
    pixel_error  : str or None — reason if pixel_array is None
    ww           : float or None
    wl           : float or None
    fps          : float — playback FPS for multi-frame / video
    """
    _ensure_pydicom()
    ds = pydicom.dcmread(filepath, force=True)

    offsets = _collect_offsets(filepath)

    # --- tag tree: File Meta (0002,xxxx) 먼저, 그 다음 main dataset ---
    nodes = []
    if hasattr(ds, 'file_meta') and ds.file_meta:
        nodes.extend(_build_nodes(ds.file_meta, offsets))
    nodes.extend(_build_nodes(ds, offsets))

    with open(filepath, 'rb') as fh:
        raw_bytes = fh.read()

    # --- transfer syntax ---
    ts_uid = ''
    if hasattr(ds, 'file_meta') and hasattr(ds.file_meta, 'TransferSyntaxUID'):
        ts_uid = str(ds.file_meta.TransferSyntaxUID)

    pixel_array = None
    pixel_error = None
    fps         = _get_fps(ds)

    if ts_uid in _VIDEO_TRANSFER_SYNTAXES:
        try:
            pixel_array, fps = _decode_video(ds)
        except Exception as e:
            import traceback, pathlib
            log = pathlib.Path(tempfile.gettempdir()) / 'hyetoria_error.log'
            log.write_text(f'ts_uid={ts_uid}\n{traceback.format_exc()}', encoding='utf-8')
            pixel_error = f'비디오 디코딩 실패: {e}\n(로그: {log})'
    else:
        pixel_array, pixel_error = _get_pixel_array(ds)

    # --- WW / WL ---
    ww = _scalar(getattr(ds, 'WindowWidth',  None))
    wl = _scalar(getattr(ds, 'WindowCenter', None))

    return nodes, raw_bytes, pixel_array, pixel_error, ww, wl, fps
