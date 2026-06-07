import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#0d1117",
          surface: "#161b22",
          elev: "#21262d",
          input: "#0d1117",
        },
        border: {
          DEFAULT: "#30363d",
          muted: "#21262d",
        },
        fg: {
          DEFAULT: "#e6edf3",
          muted: "#7d8590",
          dim: "#6e7681",
        },
        accent: {
          blue: "#388bfd",
          green: "#3fb950",
          amber: "#d29922",
          red: "#f85149",
          purple: "#a371f7",
        },
        prio: {
          high: "#f85149",
          medium: "#d29922",
          low: "#3fb950",
        },
        state: {
          queue: "#1c2d3d",
          visited: "#0d2818",
          current: "#2d2208",
          filtered: "#1c1c1c",
          default: "#21262d",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
