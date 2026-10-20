import { openCallSocket } from "./callSocket";
import type { CallSocket } from "./callSocket";
import { releaseMicrophone, setFrameSink } from "./audio/mic";
import type { ReplayInfo } from "./events.gen";
import { useAppStore } from "../stores/app";
import { useCallStore } from "../stores/call";

let active: CallSocket | null = null;

/** Begin a call: switch to the Live screen and open the call socket. */
export function startCall(source: "mic" | "replay", replay: ReplayInfo | null = null): void {
  active?.close();
  const call = useCallStore.getState();
  const app = useAppStore.getState();
  call.begin(source, replay?.title ?? null);
  app.setStartError(null);
  app.setScreen("live");

  const socket = openCallSocket({
    source,
    replayId: replay?.id ?? null,
    onEvent: (event) => {
      useCallStore.getState().dispatch(event);
      if (event.type === "call.ended") finish(socket);
    },
    onOpenFailed: () => {
      finish(socket);
      useCallStore.getState().reset();
      useAppStore.getState().setStartError("Couldn't reach Tenor's server.");
      useAppStore.getState().setScreen("start");
    },
    onLost: () => {
      finish(socket);
      useCallStore.getState().markLost();
    },
  });
  active = socket;

  if (source === "mic") {
    setFrameSink((frame) => {
      if (useCallStore.getState().phase === "live") socket.sendFrame(frame);
    });
  }
}

function finish(socket: CallSocket): void {
  if (active === socket) active = null;
  releaseMicrophone();
}

export function endCall(): void {
  setFrameSink(null);
  releaseMicrophone();
  active?.stop();
}

export function swapSpeakers(): void {
  active?.swap();
}

/** Back to the Start screen with a clean call store. */
export function newCall(): void {
  active?.close();
  active = null;
  releaseMicrophone();
  useCallStore.getState().reset();
  useAppStore.getState().setScreen("start");
}
