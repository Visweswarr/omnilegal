import React, { useState } from "react";
import { NavLink, Link, useLocation } from "react-router-dom";
import {
  Globe, ShieldCheck, FileText, Radio, Users2, BookOpen, Scale, Menu, X,
  GitCompare, Library, Swords, History, Network, Mic, Highlighter,
  Compass, TrendingUp, ShieldAlert, TestTube, Target,
} from "lucide-react";

// Group 1 — original 6 flagship pillars
const NAV_ORIGINAL = [
  { to: "/atlas",        label: "Atlas",        icon: Globe       },
  { to: "/forensics",    label: "Forensics",    icon: ShieldCheck },
  { to: "/advocacy",     label: "Advocacy",     icon: FileText    },
  { to: "/live",         label: "Live",         icon: Radio       },
  { to: "/council",      label: "Council",      icon: Users2      },
  { to: "/research",     label: "Research",     icon: BookOpen    },
];

// Group 2 — Tier-2 pillars (07–12, ordered by pillar number)
const NAV_TIER2 = [
  { to: "/graph",        label: "Graph",        icon: Network     },   // Pillar 07
  { to: "/time-machine", label: "Doctrine",     icon: History     },   // Pillar 08
  { to: "/diff",         label: "Diff",         icon: GitCompare  },   // Pillar 09
  { to: "/voice",        label: "Voice",        icon: Mic         },   // Pillar 10
  { to: "/redteam",      label: "Red Team",     icon: Swords      },   // Pillar 11
  { to: "/reading",      label: "Reading",      icon: Highlighter },   // Pillar 12
];

// Group 3 — State-of-the-Art (post-ChatGPT)
const NAV_SOTA = [
  { to: "/adversarial",  label: "Adversarial",  icon: Target      },
  { to: "/arbitrage",    label: "Arbitrage",    icon: Compass     },
  { to: "/drift",        label: "Drift",        icon: TrendingUp  },
  { to: "/sentinel",     label: "Sentinel",     icon: ShieldAlert },
  { to: "/stress",       label: "Stress",       icon: TestTube    },
];

const NAV_LIBRARY = [
  { to: "/library",      label: "Library",      icon: Library     },
];

const ALL_NAV = [...NAV_ORIGINAL, ...NAV_TIER2, ...NAV_LIBRARY, ...NAV_SOTA];

export default function NavBar() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const onLanding = loc.pathname === "/";

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 border-b border-white/10 backdrop-blur-md bg-ink-900/80 ${onLanding ? "" : ""}`}
      data-testid="navbar"
    >
      <div className="px-5 md:px-8 h-16 flex items-center justify-between gap-4">
        <Link
          to="/"
          className="flex items-center gap-2.5 group shrink-0"
          data-testid="brand-link"
        >
          <Scale className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
          <span className="font-serif text-2xl tracking-tight text-paper-100 leading-none">
            OmniLegal
          </span>
          <span className="hidden md:inline-block ml-2 text-[10px] font-mono uppercase tracking-widest2 text-paper-400 border border-white/10 px-1.5 py-0.5">
            v3
          </span>
        </Link>

        <nav className="hidden xl:flex items-center gap-0.5 flex-1 overflow-x-auto">
          {ALL_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              data-testid={`nav-${label.toLowerCase().replace(/\s/g, "-")}`}
              className={({ isActive }) =>
                `px-2.5 py-2 text-xs font-medium flex items-center gap-1.5 border-b-2 transition-colors whitespace-nowrap ${
                  isActive
                    ? "text-paper-100 border-verdict-gold"
                    : "text-paper-300 border-transparent hover:text-paper-100 hover:border-white/20"
                }`
              }
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
              {label}
            </NavLink>
          ))}
        </nav>

        <button
          aria-label="Open menu"
          onClick={() => setOpen(o => !o)}
          className="xl:hidden p-2 border border-white/10 hover:border-white/30"
          data-testid="mobile-menu-btn"
        >
          {open ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
        </button>
      </div>

      {open && (
        <div className="xl:hidden border-t border-white/10 bg-ink-900 max-h-[80vh] overflow-y-auto">
          <Group title="Flagship" items={NAV_ORIGINAL} setOpen={setOpen} />
          <Group title="Tier-2"   items={NAV_TIER2}    setOpen={setOpen} />
          <Group title="Library"  items={NAV_LIBRARY}  setOpen={setOpen} />
          <Group title="State of the Art" items={NAV_SOTA} setOpen={setOpen} />
        </div>
      )}
    </header>
  );
}

function Group({ title, items, setOpen }) {
  return (
    <div>
      <div className="px-5 pt-3 pb-1 text-[10px] font-mono uppercase tracking-widest2 text-paper-500">{title}</div>
      {items.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={() => setOpen(false)}
          data-testid={`mobile-nav-${label.toLowerCase().replace(/\s/g, "-")}`}
          className={({ isActive }) =>
            `flex items-center gap-3 px-5 py-3 border-b border-white/5 text-sm ${
              isActive ? "text-paper-100 bg-ink-800" : "text-paper-300 hover:bg-ink-800/50"
            }`
          }
        >
          <Icon className="w-4 h-4" strokeWidth={1.5} />
          {label}
        </NavLink>
      ))}
    </div>
  );
}
