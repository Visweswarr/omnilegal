import React from "react";
import { Routes, Route } from "react-router-dom";
import NavBar from "./components/NavBar";
import Landing from "./pages/Landing";
import Atlas from "./pages/Atlas";
import Forensics from "./pages/Forensics";
import Advocacy from "./pages/Advocacy";
import Live from "./pages/Live";
import Council from "./pages/Council";
import Research from "./pages/Research";
import Diff from "./pages/Diff";
import Redteam from "./pages/Redteam";
import TimeMachine from "./pages/TimeMachine";
import Graph from "./pages/Graph";
import Voice from "./pages/Voice";
import Reading from "./pages/Reading";
import Library from "./pages/Library";
import Share from "./pages/Share";
import Adversarial from "./pages/Adversarial";
import Arbitrage from "./pages/Arbitrage";
import Drift from "./pages/Drift";
import Sentinel from "./pages/Sentinel";
import Stress from "./pages/Stress";
import Comparative from "./pages/Comparative";

export default function App() {
  return (
    <div className="min-h-screen bg-ink-900 text-paper-100 relative">
      <NavBar />
      <main className="pt-16 relative z-10">
        <Routes>
          <Route path="/"             element={<Landing />} />
          <Route path="/atlas"        element={<Atlas />} />
          <Route path="/forensics"    element={<Forensics />} />
          <Route path="/advocacy"     element={<Advocacy />} />
          <Route path="/live"         element={<Live />} />
          <Route path="/council"      element={<Council />} />
          <Route path="/research"     element={<Research />} />
          <Route path="/diff"         element={<Diff />} />
          <Route path="/redteam"      element={<Redteam />} />
          <Route path="/time-machine" element={<TimeMachine />} />
          <Route path="/graph"        element={<Graph />} />
          <Route path="/voice"        element={<Voice />} />
          <Route path="/reading"      element={<Reading />} />
          <Route path="/library"      element={<Library />} />
          <Route path="/share/:token" element={<Share />} />
          {/* State-of-the-Art pillars */}
          <Route path="/adversarial"  element={<Adversarial />} />
          <Route path="/arbitrage"    element={<Arbitrage />} />
          <Route path="/drift"        element={<Drift />} />
          <Route path="/sentinel"     element={<Sentinel />} />
          <Route path="/stress"       element={<Stress />} />
          <Route path="/comparative"  element={<Comparative />} />
        </Routes>
      </main>
      <footer className="border-t border-white/10 py-6 px-6 mt-24 text-xs font-mono uppercase tracking-widest2 text-paper-400 flex flex-wrap items-center justify-between gap-3">
        <span>OmniLegal v3 · Verified Legal Intelligence</span>
        <span>The Verdict · The Map · The Proof</span>
      </footer>
    </div>
  );
}
