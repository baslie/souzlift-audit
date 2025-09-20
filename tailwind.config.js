/**
 * Tailwind CSS configuration used to build the precompiled stylesheet committed to the repository.
 *
 * Developers can regenerate `backend/static/css/tailwind.min.css` by running:
 *   NODE_ENV=production npx tailwindcss -i backend/static/css/tailwind.src.css -o backend/static/css/tailwind.min.css --minify
 * when Node.js is available, or by downloading the standalone CLI binary for Tailwind.
 */
const defaultTheme = require("tailwindcss/defaultTheme");
const plugin = require("tailwindcss/plugin");

const withOpacity = (variableName) => `hsl(var(${variableName}) / <alpha-value>)`;

module.exports = {
  content: [
    "./backend/templates/**/*.html",
    "./backend/**/*.py",
  ],
  theme: {
    container: {
      center: true,
      padding: {
        DEFAULT: "1.25rem",
        sm: "1.5rem",
        lg: "2rem",
        xl: "2.5rem",
      },
      screens: {
        sm: "640px",
        md: "768px",
        lg: "1024px",
        xl: "1240px",
        "2xl": "1360px",
      },
    },
    extend: {
      colors: {
        brand: {
          50: withOpacity("--color-brand-50"),
          100: withOpacity("--color-brand-100"),
          200: withOpacity("--color-brand-200"),
          300: withOpacity("--color-brand-300"),
          400: withOpacity("--color-brand-400"),
          500: withOpacity("--color-brand-500"),
          600: withOpacity("--color-brand-600"),
          700: withOpacity("--color-brand-700"),
          800: withOpacity("--color-brand-800"),
          900: withOpacity("--color-brand-900"),
          950: withOpacity("--color-brand-950"),
        },
        ink: {
          50: withOpacity("--color-ink-50"),
          100: withOpacity("--color-ink-100"),
          200: withOpacity("--color-ink-200"),
          300: withOpacity("--color-ink-300"),
          400: withOpacity("--color-ink-400"),
          500: withOpacity("--color-ink-500"),
          600: withOpacity("--color-ink-600"),
          700: withOpacity("--color-ink-700"),
          800: withOpacity("--color-ink-800"),
          900: withOpacity("--color-ink-900"),
          950: withOpacity("--color-ink-950"),
        },
        surface: {
          DEFAULT: withOpacity("--color-surface"),
          subtle: withOpacity("--color-surface-subtle"),
          muted: withOpacity("--color-surface-muted"),
          elevated: withOpacity("--color-surface-elevated"),
          inverted: withOpacity("--color-surface-inverted"),
        },
        border: {
          DEFAULT: withOpacity("--color-border"),
          subtle: withOpacity("--color-border-subtle"),
          strong: withOpacity("--color-border-strong"),
        },
        success: {
          50: withOpacity("--color-success-50"),
          100: withOpacity("--color-success-100"),
          200: withOpacity("--color-success-200"),
          300: withOpacity("--color-success-300"),
          400: withOpacity("--color-success-400"),
          500: withOpacity("--color-success-500"),
          600: withOpacity("--color-success-600"),
          700: withOpacity("--color-success-700"),
          800: withOpacity("--color-success-800"),
          900: withOpacity("--color-success-900"),
        },
        warning: {
          50: withOpacity("--color-warning-50"),
          100: withOpacity("--color-warning-100"),
          200: withOpacity("--color-warning-200"),
          300: withOpacity("--color-warning-300"),
          400: withOpacity("--color-warning-400"),
          500: withOpacity("--color-warning-500"),
          600: withOpacity("--color-warning-600"),
          700: withOpacity("--color-warning-700"),
          800: withOpacity("--color-warning-800"),
          900: withOpacity("--color-warning-900"),
        },
        danger: {
          50: withOpacity("--color-danger-50"),
          100: withOpacity("--color-danger-100"),
          200: withOpacity("--color-danger-200"),
          300: withOpacity("--color-danger-300"),
          400: withOpacity("--color-danger-400"),
          500: withOpacity("--color-danger-500"),
          600: withOpacity("--color-danger-600"),
          700: withOpacity("--color-danger-700"),
          800: withOpacity("--color-danger-800"),
          900: withOpacity("--color-danger-900"),
        },
      },
      fontFamily: {
        sans: ["Inter", "Manrope", ...defaultTheme.fontFamily.sans],
        heading: ["Manrope", "Inter", ...defaultTheme.fontFamily.sans],
        mono: ["JetBrains Mono", ...defaultTheme.fontFamily.mono],
      },
      fontSize: {
        "display-lg": ["3rem", { lineHeight: "1.1", letterSpacing: "-0.04em", fontWeight: "700" }],
        "display-md": ["2.25rem", { lineHeight: "1.15", letterSpacing: "-0.03em", fontWeight: "700" }],
        "display-sm": ["1.875rem", { lineHeight: "1.2", letterSpacing: "-0.02em", fontWeight: "700" }],
      },
      boxShadow: {
        xs: "0 1px 2px 0 hsl(var(--color-ink-950) / 0.06)",
        soft: "0 10px 15px -12px hsl(var(--color-ink-950) / 0.2)",
        card: "0 22px 45px -24px hsl(var(--color-ink-950) / 0.28)",
      },
      borderRadius: {
        lg: "0.9rem",
        xl: "1.25rem",
        "2xl": "1.75rem",
      },
      transitionDuration: {
        250: "250ms",
      },
      ringOffsetWidth: {
        3: "3px",
      },
    },
  },
  plugins: [
    plugin(({ addVariant }) => {
      addVariant("aria-current", '&[aria-current="page"]');
      addVariant("aria-expanded", '&[aria-expanded="true"]');
      addVariant("aria-selected", '&[aria-selected="true"]');
      addVariant("state-open", '&[data-state="open"]');
      addVariant("state-closed", '&[data-state="closed"]');
      addVariant("state-loading", '&[data-state="loading"]');
    }),
  ],
};
