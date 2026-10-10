/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "media",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        // mission-control command rail (always dark)
        rail: { DEFAULT: "hsl(var(--rail))", foreground: "hsl(var(--rail-foreground))", muted: "hsl(var(--rail-muted))", hover: "hsl(var(--rail-hover))", active: "hsl(var(--rail-active))" },
        ok: { DEFAULT: "hsl(var(--ok))", bg: "hsl(var(--ok-bg))" },
        warn: { DEFAULT: "hsl(var(--warn))", bg: "hsl(var(--warn-bg))" },
        bad: { DEFAULT: "hsl(var(--bad))", bg: "hsl(var(--bad-bg))" },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 3px)",
        sm: "calc(var(--radius) - 6px)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)",
        float: "0 1px 2px rgba(16,24,40,.04), 0 12px 28px -10px rgba(16,24,40,.16)",
        pop: "0 10px 34px rgba(16,24,40,.20)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-in-right": { from: { transform: "translateX(16px)", opacity: "0" }, to: { transform: "translateX(0)", opacity: "1" } },
        "pop-in": { from: { transform: "translateY(-4px)", opacity: "0" }, to: { transform: "translateY(0)", opacity: "1" } },
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.4" } },
      },
      animation: {
        "fade-in": "fade-in .18s ease",
        "slide-in-right": "slide-in-right .2s cubic-bezier(.16,1,.3,1)",
        "pop-in": "pop-in .14s ease",
      },
    },
  },
  plugins: [],
};
