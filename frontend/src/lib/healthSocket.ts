import { wsUrl } from "./backend";
import type { HealthPing } from "./events.gen";
import { applyHealthConnecting, applyHealthEvent, applyHealthFailure, backoffSeconds, parseServerEvent } from "./healthState";
import { setHealthState, useHealthStore } from "../stores/health";

const STATUS_TIMEOUT_MS = 4000;
const PING_INTERVAL_MS = 5000;
const MAX_MISSED_PONGS = 2;

/** Starts the health connection. Returns a stop function that cleans up all timers. */
export function startHealthSocket(): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let attempt = 0;
  let missedPongs = 0;
  let statusTimer: ReturnType<typeof setTimeout> | undefined;
  let pingTimer: ReturnType<typeof setInterval> | undefined;
  let retryTimer: ReturnType<typeof setInterval> | undefined;

  const update = (fn: (s: ReturnType<typeof useHealthStore.getState>) => ReturnType<typeof useHealthStore.getState>) =>
    setHealthState(fn(useHealthStore.getState()));

  const clearTimers = () => {
    clearTimeout(statusTimer);
    clearInterval(pingTimer);
    clearInterval(retryTimer);
    statusTimer = pingTimer = retryTimer = undefined;
  };

  const fail = () => {
    if (stopped) return;
    clearTimers();
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
      ws = null;
    }
    let wait = backoffSeconds(attempt);
    attempt += 1;
    update((s) => applyHealthFailure(s, wait));
    retryTimer = setInterval(() => {
      wait -= 1;
      if (wait <= 0) {
        clearInterval(retryTimer);
        retryTimer = undefined;
        connect();
      } else {
        update((s) => ({ ...s, retryInSec: wait }));
      }
    }, 1000);
  };

  const connect = () => {
    if (stopped) return;
    update(applyHealthConnecting);
    missedPongs = 0;
    let socket: WebSocket;
    try {
      socket = new WebSocket(wsUrl("/ws/health"));
    } catch {
      fail();
      return;
    }
    ws = socket;
    statusTimer = setTimeout(fail, STATUS_TIMEOUT_MS);

    socket.onmessage = (msg) => {
      const event = parseServerEvent(String(msg.data));
      if (!event) return;
      if (event.type === "health.status") {
        clearTimeout(statusTimer);
        statusTimer = undefined;
        attempt = 0;
        if (!pingTimer) {
          const sendPing = () => {
            if (missedPongs >= MAX_MISSED_PONGS) {
              fail();
              return;
            }
            const ping: HealthPing = {
              type: "health.ping",
              ts: new Date().toISOString(),
              client_sent_ms: performance.now(),
            };
            missedPongs += 1;
            socket.send(JSON.stringify(ping));
          };
          // Ping right away so response time shows without waiting a full interval.
          sendPing();
          pingTimer = setInterval(sendPing, PING_INTERVAL_MS);
        }
      } else if (event.type === "health.pong") {
        missedPongs = 0;
      }
      update((s) => applyHealthEvent(s, event, Date.now(), performance.now()));
    };
    socket.onclose = fail;
    socket.onerror = fail;
  };

  connect();

  return () => {
    stopped = true;
    clearTimers();
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      ws.close();
      ws = null;
    }
  };
}
