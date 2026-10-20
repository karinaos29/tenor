import { describe, expect, it } from "vitest";
import { Downsampler, FrameAccumulator, dbfsToLevel, floatToInt16, rmsDbfs } from "./pcm";

describe("Downsampler", () => {
  it("48k -> 16k averages triples and keeps remainder across blocks", () => {
    const d = new Downsampler(48000);
    const input = Float32Array.from({ length: 480 }, (_, i) => (i % 3) / 3); // 0, .333, .667
    // Feed in uneven 128-ish blocks
    const out: number[] = [];
    for (let i = 0; i < 480; i += 128) out.push(...d.process(input.subarray(i, Math.min(480, i + 128))));
    expect(out).toHaveLength(160);
    for (const v of out) expect(v).toBeCloseTo(1 / 3, 5);
  });

  it("44.1k -> 16k gives about the right count", () => {
    const d = new Downsampler(44100);
    let n = 0;
    for (let i = 0; i < 441; i++) n += d.process(new Float32Array(100)).length;
    expect(Math.abs(n - 16000)).toBeLessThanOrEqual(1);
  });

  it("preserves a constant signal", () => {
    const out = new Downsampler(44100).process(new Float32Array(1000).fill(0.5));
    for (const v of out) expect(v).toBeCloseTo(0.5, 5);
  });
});

describe("floatToInt16", () => {
  it("clips and scales", () => {
    const out = floatToInt16([0, 1, -1, 2, -3, 0.5]);
    expect(Array.from(out)).toEqual([0, 32767, -32768, 32767, -32768, 16384]);
  });
});

describe("FrameAccumulator", () => {
  it("emits exact 1280-sample frames across uneven blocks", () => {
    const acc = new FrameAccumulator();
    const frames: Int16Array[] = [];
    let total = 0;
    for (const n of [100, 1000, 500, 1280, 3, 2000]) {
      const block = new Int16Array(n).map((_, i) => (total + i) % 1000);
      total += n;
      frames.push(...acc.push(block));
    }
    expect(frames).toHaveLength(Math.floor(total / 1280));
    expect(frames.every((f) => f.length === 1280)).toBe(true);
    expect(frames[1][0]).toBe(1280 % 1000);
  });
});

describe("rmsDbfs", () => {
  it("silence is the floor, full scale is 0", () => {
    expect(rmsDbfs(new Float32Array(100))).toBe(-100);
    expect(rmsDbfs([])).toBe(-100);
    expect(rmsDbfs(new Float32Array(100).fill(1))).toBeCloseTo(0, 5);
    expect(rmsDbfs(new Int16Array(100).fill(-32768), 32768)).toBeCloseTo(0, 5);
    expect(rmsDbfs(new Float32Array(100).fill(0.5))).toBeCloseTo(-6.02, 1);
  });
  it("maps to a meter level", () => {
    expect(dbfsToLevel(-100)).toBe(0);
    expect(dbfsToLevel(-30)).toBeCloseTo(0.5);
    expect(dbfsToLevel(0)).toBe(1);
  });
});
