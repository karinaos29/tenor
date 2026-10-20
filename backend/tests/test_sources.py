import asyncio
import math
import time

import numpy as np
import pytest

from audio.sources import FRAME_BYTES, FRAME_SAMPLES, FileSource, MicSource, frame_dbfs
from tests.fakes import pcm, write_wav


async def collect(source) -> list[bytes]:
    return [f async for f in source.frames()]


def test_file_source_frames_and_zero_padding(tmp_path):
    path = write_wav(tmp_path / "a.wav", 0.5)  # 8000 samples = 6.25 frames
    n = 8000
    frames = asyncio.run(collect(FileSource(path, realtime=False)))
    assert len(frames) == math.ceil(n / FRAME_SAMPLES) == 7
    assert all(len(f) == FRAME_BYTES == 2560 for f in frames)
    tail = frames[-1]
    used = (n - 6 * FRAME_SAMPLES) * 2
    assert tail[used:] == b"\x00" * (FRAME_BYTES - used)
    assert any(tail[:used])  # the real audio part is not zeroed


def test_file_source_exact_multiple_has_no_extra_frame(tmp_path):
    path = write_wav(tmp_path / "a.wav", 0.4)  # exactly 5 frames
    assert len(asyncio.run(collect(FileSource(path, realtime=False)))) == 5


def test_file_source_duration(tmp_path):
    assert FileSource(write_wav(tmp_path / "a.wav", 0.4)).duration_s == pytest.approx(0.4)


@pytest.mark.parametrize("kwargs", [{"rate": 8000}, {"channels": 2}])
def test_file_source_rejects_wrong_format(tmp_path, kwargs):
    path = write_wav(tmp_path / "bad.wav", 0.2, **kwargs)
    with pytest.raises(ValueError, match="16 kHz mono"):
        FileSource(path)


def test_file_source_realtime_pacing(tmp_path):
    path = write_wav(tmp_path / "a.wav", 0.4)

    async def main():
        t0 = time.monotonic()
        frames = await collect(FileSource(path, realtime=True))
        return len(frames), time.monotonic() - t0

    n, elapsed = asyncio.run(main())
    assert n == 5
    assert 0.35 <= elapsed <= 0.7


def test_file_source_close_stops_iteration(tmp_path):
    path = write_wav(tmp_path / "a.wav", 1.0)

    async def main():
        src = FileSource(path, realtime=False)
        got = []
        async for f in src.frames():
            got.append(f)
            if len(got) == 3:
                src.close()
        return got

    assert len(asyncio.run(main())) == 3


def test_mic_source_rechunks_uneven_pushes():
    data = pcm(0.4, -20)  # 5 frames
    assert len(data) == 5 * FRAME_BYTES

    async def main():
        mic = MicSource()
        pos = 0
        for size in (100, 3000, 1, 4999):
            mic.push(data[pos : pos + size])
            pos += size
        mic.push(data[pos:])
        mic.close()
        return await collect(mic)

    frames = asyncio.run(main())
    assert len(frames) == 5
    assert all(len(f) == FRAME_BYTES for f in frames)
    assert b"".join(frames) == data


def test_mic_source_partial_frame_is_not_emitted():
    async def main():
        mic = MicSource()
        mic.push(b"\x00" * (FRAME_BYTES - 2))
        mic.close()
        return await collect(mic)

    assert asyncio.run(main()) == []


def test_mic_source_close_ends_iteration_and_ignores_later_pushes():
    async def main():
        mic = MicSource()

        async def reader():
            return await collect(mic)

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.01)
        mic.close()
        mic.push(b"\x00" * FRAME_BYTES)
        return await asyncio.wait_for(task, 1)

    assert asyncio.run(main()) == []


def test_mic_source_overflow_drops_oldest():
    async def main():
        mic = MicSource(max_buffered_frames=3)
        for i in range(6):
            mic.push(bytes([i + 1]) * FRAME_BYTES)
        mic.close()
        return await collect(mic)

    frames = asyncio.run(main())
    # close() makes room for its end marker by dropping one more frame from the full queue
    assert [f[0] for f in frames] == [5, 6]


def test_frame_dbfs_silence_and_full_scale():
    assert frame_dbfs(b"\x00" * FRAME_BYTES) == -100.0
    assert frame_dbfs(b"") == -100.0
    square = np.where(np.arange(FRAME_SAMPLES) % 2 == 0, 32767, -32768).astype("<i2").tobytes()
    assert frame_dbfs(square) == pytest.approx(0.0, abs=0.01)


def test_frame_dbfs_matches_pcm_helper():
    for level in (-10, -20, -35):
        assert frame_dbfs(pcm(0.08, level)) == pytest.approx(level, abs=0.1)
