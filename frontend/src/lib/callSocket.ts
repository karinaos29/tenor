import type { CallStart, CallStop, SpeakersSwap, TenorEvent } from "./events.gen";
import { wsUrl } from "./backend";
import { parseCallEvent } from "./callState";

export const OPEN_TIMEOUT_MS = 4000;
export const STOP_GRACE_MS = 3000;

export interface CallSocketOptions {
  source: "mic" | "replay";
  replayId: string | null;
  onEvent: (event: TenorEvent) => void;
  /** The socket never opened within the timeout (or failed before opening). */
  onOpenFailed: () => void;
  /** The socket closed without call.ended and the user hadn't asked to stop. */
  onLost: () => void;
}

export interface CallSocket {
  sendFrame: (frame: Int16Array) => void;
  swap: () => void;
  /** Ask the server to end the call; the socket stays open until call.ended (max 3 s). */
  stop: () => void;
  close: () => void;
}

export function openCallSocket(opts: CallSocketOptions): CallSocket {
  let opened = false;
  let ended = false;
  let stopping = false;
  let closed = false;
  let openTimer: ReturnType<typeof setTimeout> | undefined;
  let stopTimer: ReturnType<typeof setTimeout> | undefined;

  const ws = new WebSocket(wsUrl("/ws/call"));
  ws.binaryType = "arraybuffer";

  const detach = () => {
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
  };
  const shutdown = () => {
    closed = true;
    clearTimeout(openTimer);
    clearTimeout(stopTimer);
    detach();
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  };
  const syntheticEnd = () => {
    ended = true;
    opts.onEvent({ ts: new Date().toISOString(), type: "call.ended", reason: "user", detail: "" });
    shutdown();
  };
  const sendJson = (msg: CallStart | CallStop | SpeakersSwap) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };
  const failBeforeOpen = () => {
    if (closed) return;
    shutdown();
    opts.onOpenFailed();
  };

  openTimer = setTimeout(failBeforeOpen, OPEN_TIMEOUT_MS);

  ws.onopen = () => {
    opened = true;
    clearTimeout(openTimer);
    sendJson({ type: "call.start", ts: new Date().toISOString(), source: opts.source, replay_id: opts.replayId });
  };
  ws.onmessage = (msg) => {
    if (typeof msg.data !== "string") return;
    const event = parseCallEvent(msg.data);
    if (!event) return;
    opts.onEvent(event);
    if (event.type === "call.ended") {
      ended = true;
      shutdown();
    }
  };
  const onGone = () => {
    if (closed || ended) return;
    if (!opened) return failBeforeOpen();
    if (stopping) return syntheticEnd();
    shutdown();
    opts.onLost();
  };
  ws.onclose = onGone;
  ws.onerror = onGone;

  return {
    sendFrame: (frame) => {
      if (opened && !stopping && !closed && ws.readyState === WebSocket.OPEN) ws.send(frame.buffer as ArrayBuffer);
    },
    swap: () => sendJson({ type: "speakers.swap", ts: new Date().toISOString() }),
    stop: () => {
      if (closed || stopping) return;
      stopping = true;
      sendJson({ type: "call.stop", ts: new Date().toISOString() });
      stopTimer = setTimeout(() => {
        if (!ended && !closed) syntheticEnd();
      }, STOP_GRACE_MS);
    },
    close: shutdown,
  };
}
