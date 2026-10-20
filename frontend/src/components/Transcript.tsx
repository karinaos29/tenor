import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { swapSpeakers } from "../lib/callSession";
import { displayRole, formatClock } from "../lib/callState";
import type { Utterance } from "../lib/events.gen";
import { highlightSegments, offerPhrasesFor } from "../lib/highlight";
import { useCallStore } from "../stores/call";

function TranscriptStatus() {
  const { phase, transcriber, lostMessage } = useCallStore();
  let text: string | null = null;
  let tone = "muted";
  if (phase === "lost") {
    text = lostMessage;
    tone = "warn";
  } else if (transcriber.state === "connecting" && phase !== "ended") {
    text = "Connecting to the speech service…";
  } else if (transcriber.state === "reconnecting") {
    text = "Transcription paused. Reconnecting…";
    tone = "warn";
  } else if (transcriber.state === "unavailable") {
    text = "Transcription is off: couldn't reach the speech service." + (transcriber.detail === "no_key" ? " The speech-to-text key is missing." : "");
    tone = "warn";
  }
  return (
    <div aria-live="polite" className="transcript__status">
      {text && <p className={tone}>{text}</p>}
    </div>
  );
}

/** "pending" = a partial line: speech-to-text speaker numbers on interim results are
 * unreliable, so a line only takes a role (and its voice style) once it's final. */
type LineVoice = "caller" | "user" | "pending";

const WHO: Record<LineVoice, string> = { caller: "Caller", user: "You", pending: "Speaking…" };

function Line({ u, voice, phrases = [] }: { u: Utterance; voice: LineVoice; phrases?: string[] }) {
  const body = (
    <>
      <p className="line__meta">
        <span className="line__who">{WHO[voice]}</span>
        <span className="line__time numbers">{formatClock(u.t_start * 1000)}</span>
      </p>
      <p className="line__text">
        {voice === "caller" && phrases.length > 0
          ? highlightSegments(u.text, phrases).map((seg, i) =>
              seg.mark ? (
                <mark key={i} className="term" title="Part of the offer">{seg.text}</mark>
              ) : (
                <span key={i}>{seg.text}</span>
              ),
            )
          : u.text}
        {voice === "pending" ? "…" : ""}
      </p>
    </>
  );
  if (voice === "pending") return <div className="line line--pending">{body}</div>;
  return (
    <motion.div className={`line line--${voice}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }}>
      {body}
    </motion.div>
  );
}

export function Transcript() {
  const { utterances, userIndices, labelsLocked, offer } = useCallStore();
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(false);

  const finals = utterances.filter((u) => u.is_final);
  const partials = utterances.filter((u) => !u.is_final);

  const toBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  useLayoutEffect(() => {
    if (stick.current) toBottom();
  }, [utterances, toBottom]);

  useEffect(() => {
    stick.current = true;
  }, []);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
    stick.current = atBottom;
    setAway(!atBottom);
  };

  return (
    <section className="card transcript" aria-labelledby="transcript-title">
      <div className="transcript__head">
        <h2 id="transcript-title" className="card__title">Live transcript</h2>
        <div className="transcript__tools">
          {labelsLocked && <span className="muted transcript__set">Labels set by you</span>}
          <button
            className="btn btn--secondary btn--small"
            title="Use this if your words show up as the caller's"
            onClick={swapSpeakers}
          >
            Swap speakers
          </button>
        </div>
      </div>
      <TranscriptStatus />
      <div className="transcript__body" ref={scroller} onScroll={onScroll}>
        {utterances.length === 0 && <p className="muted">Words appear here as people speak.</p>}
        <div role="log" aria-live="polite">
          {finals.map((u) => (
            <Line key={u.id} u={u} voice={displayRole(u, userIndices)} phrases={offerPhrasesFor(offer, u.id)} />
          ))}
        </div>
        {partials.map((u) => (
          <Line key={u.id} u={u} voice="pending" />
        ))}
      </div>
      {away && (
        <button
          className="btn btn--small jump"
          onClick={() => {
            stick.current = true;
            setAway(false);
            toBottom();
          }}
        >
          Jump to latest
        </button>
      )}
    </section>
  );
}
