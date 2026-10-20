import { useEffect } from "react";
import { MotionConfig } from "framer-motion";
import { LiveScreen } from "./components/LiveScreen";
import { StartScreen } from "./components/StartScreen";
import { releaseMicrophone } from "./lib/audio/mic";
import { startHealthSocket } from "./lib/healthSocket";
import { useAppStore } from "./stores/app";

export function App() {
  const screen = useAppStore((s) => s.screen);
  useEffect(() => startHealthSocket(), []);
  useEffect(() => releaseMicrophone, []);
  return <MotionConfig reducedMotion="user">{screen === "live" ? <LiveScreen /> : <StartScreen />}</MotionConfig>;
}
