/** Pure audio helpers. Used by the AudioWorklet and unit-tested without any browser audio. */

export const TARGET_RATE = 16000;
export const FRAME_SAMPLES = 1280; // 80 ms at 16 kHz

/**
 * Streaming downsampler. Each output sample is the average of the input samples in its window
 * (fractional ratios like 44100/16000 are handled by weighting the boundary sample).
 * State carries across calls, so any block size (e.g. 128) works.
 */
export class Downsampler {
  private readonly ratio: number;
  private sum = 0;
  private filled = 0;

  constructor(inputRate: number, outputRate: number = TARGET_RATE) {
    this.ratio = inputRate / outputRate;
  }

  process(input: ArrayLike<number>): Float32Array {
    const out: number[] = [];
    const eps = 1e-9;
    for (let i = 0; i < input.length; i++) {
      const x = input[i];
      let take = 1;
      while (take > eps) {
        const room = this.ratio - this.filled;
        if (take < room - eps) {
          this.sum += x * take;
          this.filled += take;
          take = 0;
        } else {
          this.sum += x * room;
          out.push(this.sum / this.ratio);
          this.sum = 0;
          this.filled = 0;
          take -= room;
        }
      }
    }
    return Float32Array.from(out);
  }
}

/** Float32 [-1, 1] to Int16, clipping anything outside the range. */
export function floatToInt16(input: ArrayLike<number>): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
  }
  return out;
}

/** Collects Int16 samples and emits exact fixed-size frames. */
export class FrameAccumulator {
  private buf: Int16Array;
  private len = 0;

  constructor(private readonly frameSize: number = FRAME_SAMPLES) {
    this.buf = new Int16Array(frameSize);
  }

  push(samples: Int16Array): Int16Array[] {
    const frames: Int16Array[] = [];
    let offset = 0;
    while (offset < samples.length) {
      const n = Math.min(this.frameSize - this.len, samples.length - offset);
      this.buf.set(samples.subarray(offset, offset + n), this.len);
      this.len += n;
      offset += n;
      if (this.len === this.frameSize) {
        frames.push(this.buf);
        this.buf = new Int16Array(this.frameSize);
        this.len = 0;
      }
    }
    return frames;
  }
}

/** RMS level in dBFS (0 = full scale). Silence returns the floor, -100. */
export function rmsDbfs(samples: ArrayLike<number>, fullScale = 1): number {
  if (samples.length === 0) return -100;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = samples[i] / fullScale;
    sum += v * v;
  }
  const rms = Math.sqrt(sum / samples.length);
  if (rms <= 0) return -100;
  return Math.max(-100, 20 * Math.log10(rms));
}

/** Map dBFS (-60..0) to a 0..1 meter fill. */
export function dbfsToLevel(dbfs: number): number {
  return Math.max(0, Math.min(1, (dbfs + 60) / 60));
}
