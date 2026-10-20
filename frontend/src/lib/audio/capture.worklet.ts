import { Downsampler, FrameAccumulator, floatToInt16, rmsDbfs } from "./pcm";

// Minimal AudioWorklet globals (not in the DOM lib).
declare const sampleRate: number;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(name: string, ctor: new () => AudioWorkletProcessor): void;

export interface CaptureMessage {
  frame: Int16Array;
  dbfs: number;
}

class CaptureProcessor extends AudioWorkletProcessor {
  private down = new Downsampler(sampleRate);
  private acc = new FrameAccumulator();

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (channel) {
      const frames = this.acc.push(floatToInt16(this.down.process(channel)));
      for (const frame of frames) {
        const msg: CaptureMessage = { frame, dbfs: rmsDbfs(frame, 32768) };
        this.port.postMessage(msg, [frame.buffer]);
      }
    }
    return true;
  }
}

registerProcessor("tenor-capture", CaptureProcessor);
