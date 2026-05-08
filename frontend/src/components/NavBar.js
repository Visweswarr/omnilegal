import React, { useState } from "react";
import { NavLink, Link, useLocation } from "react-router-dom";
import { Globe, ShieldCheck, FileText, Radio, Users2, BookOpen, Scale, Menu, X } from "lucide-react";

const NAV = [
  { to: "/atlas",     label: "Atlas",     icon: Globe       },
  { to: "/forensics", label: "Forensics", icon: ShieldCheck },
  { to: "/advocacy",  label: "Advocacy",  icon: FileText    },
  { to: "/live",      label: "Live",      icon: Radio       },
  { to: "/council",   label: "Council",   icon: Users2      },
  { to: "/research",  label: "Research",  icon: BookOpen    },
];

export default function NavBar() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const onLanding = loc.pathname === "/";

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 border-b border-white/10 backdrop-blur-md bg-ink-900/80 ${onLanding ? "" : ""}`}
      data-testid="navbar"
    >
      <div className="px-5 md:px-8 h-16 flex items-center justify-between">
        <Link
          to="/"
          className="flex items-center gap-2.5 group"
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

        <nav className="hidden md:flex items-center gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              data-testid={`nav-${label.toLowerCase()}`}
              className={({ isActive }) =>
                `px-3 py-2 text-sm font-medium flex items-center gap-2 border-b-2 transition-colors ${
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
          className="md:hidden p-2 border border-white/10 hover:border-white/30"
          data-testid="mobile-menu-btn"
        >
          {open ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
        </button>
      </div>

      {open && (
        <div className="md:hidden border-t border-white/10 bg-ink-900">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              data-testid={`mobile-nav-${label.toLowerCase()}`}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-3 border-b border-white/5 text-sm ${
                  isActive
                    ? "text-paper-100 bg-ink-800"
                    : "text-paper-300 hover:bg-ink-800/50"
                }`
              }
            >
              <Icon className="w-4 h-4" strokeWidth={1.5} />
              {label}
            </NavLink>
          ))}
        </div>
      )}
    </header>
  );
}
