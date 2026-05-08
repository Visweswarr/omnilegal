/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          50:  "#f8f8f8",
          100: "#e6e6e6",
          200: "#cfcfcf",
          300: "#a3a3a3",
          400: "#666666",
          500: "#4a4a4a",
          600: "#2a2a2a",
          700: "#1a1a1a",
          800: "#121212",
          900: "#0a0a0a",
        },
        paper: {
          50:  "#f3f1ec",
          100: "#ece8df",
          200: "#dcd6c8",
          300: "#bdb59f",
          400: "#928a72",
        },
        verdict: {
          gold:    "#D97706",
          amber:   "#F59E0B",
          red:     "#DC2626",
          green:   "#16A34A",
          gray:    "#525252",
        },
      },
      fontFamily: {
        serif: ['Newsreader', 'ui-serif', 'Georgia', 'serif'],
        sans:  ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono:  ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      letterSpacing: {
        widest2: '0.25em',
      },
      borderRadius: {
        none: "0",
        DEFAULT: "0",
      },
      animation: {
        "stamp": "stamp 0.45s ease-out forwards",
        "pulse-slow": "pulse 2.4s ease-in-out infinite",
        "fade-up": "fadeUp 0.45s ease-out forwards",
      },
      keyframes: {
        stamp: {
          "0%":   { transform: "scale(1.5) rotate(-2deg)", opacity: "0" },
          "60%":  { transform: "scale(0.96) rotate(0.5deg)", opacity: "1" },
          "100%": { transform: "scale(1) rotate(0deg)",   opacity: "1" },
        },
        fadeUp: {
          "0%":   { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)",    opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};
