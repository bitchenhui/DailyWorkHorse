"""把帧序列编码成视频文件。

帧是逐个消费的，全程不在内存里堆整段视频：1080×1920 一帧就是 6MB，
二十多秒的量足以把内存吃穿。所以这里把原始像素直接管道给 ffmpeg，
而不是先落一堆 PNG 再合成。

ffmpeg 从两个地方找：系统 PATH（GitHub Actions 的 ubuntu 镜像自带），
以及 ``imageio-ffmpeg`` 这个自带二进制的 pip 包（本地开发用）。
两处都没有就降级成 GIF——GIF 只是让人能看见画面，不是能发布的成品，
所以顺手压掉尺寸和帧率，否则文件大到没法预览。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from itertools import chain
from pathlib import Path
from typing import Iterable, Iterator

from PIL import Image

FPS = 25
# GIF 只作降级预览，按这个尺寸和帧率压，免得单文件上百 MB。
GIF_WIDTH = 540
GIF_FPS = 12


def ffmpeg_binary() -> str | None:
    """找一个可用的 ffmpeg，找不到返回 None。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - 包在但二进制缺失时会抛各种异常
        return None


def preferred_suffix() -> str:
    """当前环境能产出的最佳格式。调用方据此决定文件名。"""
    return ".mp4" if ffmpeg_binary() else ".gif"


def _mp4_command(binary: str, width: int, height: int, fps: int, path: Path) -> list[str]:
    return [
        binary,
        "-y",
        "-loglevel", "error",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        # 补一条无声音轨：部分平台会拒收没有音频流的视频。
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "21",
        # yuv420p 是手机端播放器的通用底线，缺了它有些客户端只出声不出画。
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "64k",
        # 让 moov 原子前置，边下边播而不是下完才开始播。
        "-movflags", "+faststart",
        str(path),
    ]


def _write_mp4(
    frames: Iterator[Image.Image], path: Path, fps: int, binary: str
) -> int:
    first = next(frames, None)
    if first is None:
        raise ValueError("没有可编码的帧")

    width, height = first.size
    command = _mp4_command(binary, width, height, fps, path)

    # stderr 写临时文件而不是管道：管道缓冲区写满会和我们的写入互相阻塞，
    # 出错时又需要看得到 ffmpeg 说了什么。
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
        )
        count = 0
        try:
            assert process.stdin is not None
            for frame in chain([first], frames):
                process.stdin.write(frame.convert("RGB").tobytes())
                count += 1
            process.stdin.close()
        except BrokenPipeError as error:
            process.wait()
            errors.seek(0)
            raise RuntimeError(
                f"ffmpeg 中途退出: {errors.read().decode('utf-8', 'replace')}"
            ) from error

        if process.wait() != 0:
            errors.seek(0)
            raise RuntimeError(
                f"ffmpeg 编码失败: {errors.read().decode('utf-8', 'replace')}"
            )
    return count


def _write_gif(frames: Iterator[Image.Image], path: Path, fps: int) -> int:
    """降级路径：抽帧缩图存 GIF，只为看得见，不为发布。"""
    step = max(1, round(fps / GIF_FPS))
    thumbs: list[Image.Image] = []
    for index, frame in enumerate(frames):
        if index % step:
            continue
        height = round(frame.height * GIF_WIDTH / frame.width)
        thumbs.append(frame.convert("RGB").resize((GIF_WIDTH, height)))

    if not thumbs:
        raise ValueError("没有可编码的帧")

    thumbs[0].save(
        path,
        save_all=True,
        append_images=thumbs[1:],
        duration=round(1000 / GIF_FPS),
        loop=0,
        optimize=True,
    )
    return len(thumbs)


def write(frames: Iterable[Image.Image], path: Path, fps: int = FPS) -> Path:
    """按 ``path`` 的后缀编码；后缀与当前环境能力不符时改写后缀。

    返回实际写出的路径——降级会改变扩展名，调用方需要知道真实文件名。
    """
    stream = iter(frames)
    binary = ffmpeg_binary()

    if path.suffix.lower() == ".mp4" and binary:
        _write_mp4(stream, path, fps, binary)
        return path

    target = path if path.suffix.lower() == ".gif" else path.with_suffix(".gif")
    _write_gif(stream, target, fps)
    return target
