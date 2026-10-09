import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "hsl(var(--bg))",
        card: "hsl(var(--card))",
        fg: "hsl(var(--fg))",
        muted: "hsl(var(--muted))",
        border: "hsl(var(--border))",
        brand: { DEFAULT: "hsl(var(--brand))", fg: "hsl(var(--brand-fg))" },
        danger: "hsl(var(--danger))",
        success: "hsl(var(--success))",
      },
      // Text variants of the accent colours: slightly darker (light mode) / lighter (dark mode) so text keeps AA contrast.
      textColor: { brand: { DEFAULT: "hsl(var(--brand-text))", fg: "hsl(var(--brand-fg))" }, danger: "hsl(var(--danger-text))", success: "hsl(var(--success-text))" },
      borderRadius: { xl: "0.875rem", "2xl": "1.25rem" },
      boxShadow: { card: "0 1px 2px hsl(0 0% 0% / 0.05), 0 4px 12px hsl(0 0% 0% / 0.04)" },
    },
  },
  plugins: [],
};
export default config;
