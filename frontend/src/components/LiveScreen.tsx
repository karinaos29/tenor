import { motion } from "framer-motion";
import { CallStrip } from "./CallStrip";
import { RightRail } from "./RightRail";
import { SafetyBanner } from "./SafetyBanner";
import { Transcript } from "./Transcript";
import "./LiveScreen.css";

export function LiveScreen() {
  return (
    <motion.main className="live" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }}>
      <h1 className="sr-only">Live call</h1>
      <CallStrip />
      <SafetyBanner />
      <div className="live__grid">
        <Transcript />
        <RightRail />
      </div>
    </motion.main>
  );
}
