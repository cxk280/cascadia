import type { Config } from "tailwindcss";

// Tokens mirror docs/design/landing-hero-spec.md §2.2 and Figma's
// `Cascadia Colors` collection so the dashboard stays visually consistent
// with the landing page and Figma mocks.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0B0E13",
          surface: "#11151C",
          raised: "#171C26",
        },
        fg: {
          DEFAULT: "#E6E8EC",
          muted: "#9098A8",
          subtle: "#5E6675",
        },
        border: {
          DEFAULT: "#1F2632",
          strong: "#2A3344",
        },
        accent: {
          DEFAULT: "#5AE3D6",
          warn: "#FFB454",
          danger: "#FF6B6B",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular"],
      },
    },
  },
  plugins: [],
};
export default config;
