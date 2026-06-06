import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        "bg-primary":  "#0D0B08",
        "bg-surface":  "#1A1712",
        "bg-elevated": "#252017",
        "accent-orange": "#E8820C",
        "accent-gold":   "#C9A227",
        "text-warm":     "#F0EAD6",
        "text-muted":    "#9A8F78",
        "border-dark":   "#2E2920",
      },
      fontFamily: {
        display: ["'Playfair Display'", "serif"],
        body:    ["'DM Sans'", "system-ui", "sans-serif"],
        mono:    ["'JetBrains Mono'", "monospace"],
      },
      animation: {
        "fade-in": "fade-in 0.25s ease-out both",
        "slide-up": "slideUp 0.3s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
