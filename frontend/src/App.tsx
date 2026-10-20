import { useEffect } from "react";
import { ConnectionCard } from "./components/ConnectionCard";
import { startHealthSocket } from "./lib/healthSocket";

export function App() {
  useEffect(() => startHealthSocket(), []);
  return <ConnectionCard />;
}
