import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { SecretAlert } from "../lib/callState";
import { useCallStore } from "../stores/call";

interface Copy {
  tag: string;
  title: string;
  body: string;
  say: string;
}

/** Plain words for each state. The "say" lines match backend/pipeline/suggestions.py. */
export function bannerCopy(a: SecretAlert): Copy {
  if (a.sharing) {
    return {
      tag: "Stop",
      title: "Stop. Don't say any more.",
      body: "Already said it? Call your bank on the number on your card.",
      say: "Sorry, I won't read that out. I'm hanging up now.",
    };
  }
  if (a.level === "check") {
    return {
      tag: "Check first",
      title: "Check who's calling first.",
      body: `The caller asked for your ${a.label}. Call back on a number you look up yourself.`,
      say: "I'll call you back on a number I look up myself.",
    };
  }
  if (a.kind === "remote_access") {
    return {
      tag: "Warning",
      title: "Don't let them onto your computer.",
      body: "The caller asked for access to your computer. No real bank or firm needs it on a call.",
      say: "I don't let anyone onto my computer. Goodbye.",
    };
  }
  return {
    tag: "Warning",
    title: "Don't read it out.",
    body: `The caller asked for your ${a.label}. No real bank or firm needs it on a call.`,
    say: "I don't give that out on the phone. Goodbye.",
  };
}

/** Pinned under the call strip when someone asks for a private detail. Silent; covers nothing. */
export function SafetyBanner() {
  const secret = useCallStore((s) => s.secret);
  const hide = useCallStore((s) => s.hideSecret);
  const reduce = useReducedMotion();
  const shown = secret !== null && !secret.hidden;
  const copy = shown ? bannerCopy(secret) : null;
  const tone = secret?.level === "check" && !secret.sharing ? "warn" : "danger";
  return (
    <div role="alert">
      <AnimatePresence initial={false}>
        {copy && (
          <motion.section
            key={`${secret?.kind}-${secret?.sharing}`}
            className={`safety safety--${tone}`}
            aria-label="Warning about private details"
            initial={reduce ? false : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className="safety__text">
              <p className="safety__head">
                <span className="safety__tag">{copy.tag}</span>
                <span className="safety__title">{copy.title}</span>
              </p>
              <p className="safety__body">{copy.body}</p>
            </div>
            <div className="safety__say">
              <p className="sug__label">Say this</p>
              <p className="sug__say">“{copy.say}”</p>
            </div>
            <button className="btn btn--secondary btn--small safety__hide" onClick={hide}>
              Hide
            </button>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
}
