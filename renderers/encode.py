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
from typing import TYPE_CHECKING, Iterable, Iterator

from PIL import Image

from core.console import safe_print

if TYPE_CHECKING:
    from renderers.audio import AudioSpec

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
        # 先补一条无声音轨保底：部分平台会拒收没有音频流的视频。若随后混音成功，
        # 这条会被带旁白+BGM 的音轨整体替换掉；混音失败则留着它，成片依旧有声道。
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


def _mux_command(
    binary: str,
    video: Path,
    out: Path,
    bgm: Path | None,
    narration: Path | None,
    bgm_volume: float,
) -> list[str]:
    """在已成片的无声视频上叠加旁白与背景音乐，混成一条音轨。

    结构：一条无限静音垫底（保证音轨永远不短于画面）+ 循环的 BGM（压低音量）
    + 一遍旁白，三者 ``amix`` 相加。

    ``amix`` 默认按输入数取平均（每路衰减 1/N）。老版 ffmpeg（``imageio-ffmpeg``
    自带的 4.2.2）**不认 ``normalize`` 选项**，用了会直接报错、整段混音失败。
    所以这里不写 ``normalize``，改在混完后统一 ``volume=N`` 乘回来——等价于把各路
    相加，新旧 ffmpeg 都吃。``-shortest`` 以视频时长收口，无限的音轨随画面结束而止。
    """
    inputs: list[str] = ["-i", str(video)]
    filters: list[str] = []
    labels: list[str] = []
    idx = 1

    # 无限静音垫底：BGM 缺席、或旁白比画面短时，靠它把音轨撑到画面结束，
    # 否则 -shortest 会反过来把视频截到旁白那么短。
    inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    labels.append(f"[{idx}:a]")
    idx += 1

    if bgm is not None:
        inputs += ["-stream_loop", "-1", "-i", str(bgm)]
        filters.append(f"[{idx}:a]volume={bgm_volume}[bg]")
        labels.append("[bg]")
        idx += 1

    if narration is not None:
        inputs += ["-i", str(narration)]
        labels.append(f"[{idx}:a]")
        idx += 1

    count = len(labels)
    filters.append(
        "".join(labels)
        + f"amix=inputs={count}:duration=first:dropout_transition=2[mix]"
    )
    # 乘回输入数，抵消 amix 的取平均，让旁白与 BGM 恢复到设定音量（≈ normalize=0）。
    filters.append(f"[mix]volume={count}[a]")

    return [
        binary,
        "-y",
        "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        "-shortest",
        str(out),
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


def _add_audio(binary: str, video: Path, spec: "AudioSpec") -> None:
    """给已成片的无声视频叠上旁白与 BGM，成功则原地替换。

    任何环节失败都保留那支无声成片、只记一行日志——音频是锦上添花，
    绝不能因为它把整支视频拖没（延续「发信失败不把整趟标红」的项目哲学）。
    """
    from renderers import audio as audio_mod

    narration = audio_mod.synthesize(spec.narration) if spec.narration else None
    bgm = spec.bgm
    if bgm is None and narration is None:
        return  # 既没配音也没 BGM，无声成片就是最终形态

    mixed = video.with_name(video.stem + ".mixed.mp4")
    try:
        command = _mux_command(binary, video, mixed, bgm, narration, spec.bgm_volume)
        with tempfile.TemporaryFile() as errors:
            result = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=errors
            )
            if result.returncode != 0:
                errors.seek(0)
                raise RuntimeError(errors.read().decode("utf-8", "replace"))
        mixed.replace(video)
    except Exception as exc:  # noqa: BLE001 — 混音失败降级为无声，不阻断出片
        safe_print(f"  混音失败，保留无声成片: {exc}")
        mixed.unlink(missing_ok=True)
    finally:
        # 清理临时旁白。删不掉（Windows 偶发占用等）也只是留个临时文件，
        # 绝不能让清理失败反过来把已经混好的成片带崩。
        if narration is not None:
            try:
                narration.unlink(missing_ok=True)
            except OSError:
                pass


def write(
    frames: Iterable[Image.Image],
    path: Path,
    fps: int = FPS,
    audio: "AudioSpec | None" = None,
) -> Path:
    """按 ``path`` 的后缀编码；后缀与当前环境能力不符时改写后缀。

    返回实际写出的路径——降级会改变扩展名，调用方需要知道真实文件名。

    ``audio`` 给定且能出 mp4 时，先写出无声成片再叠加旁白+BGM：无声那份始终有效，
    混音只是在它之上就地升级，失败也只是留住无声版。GIF 降级路径不带音频。
    """
    stream = iter(frames)
    binary = ffmpeg_binary()

    if path.suffix.lower() == ".mp4" and binary:
        _write_mp4(stream, path, fps, binary)
        if audio is not None:
            _add_audio(binary, path, audio)
        return path

    target = path if path.suffix.lower() == ".gif" else path.with_suffix(".gif")
    _write_gif(stream, target, fps)
    return target
