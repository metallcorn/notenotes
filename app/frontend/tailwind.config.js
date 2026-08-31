/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      // Семантические токены поверх CSS-переменных (index.css: светлые
      // значения под :root, тёмные — под .dark). НЕ переопределяем сами
      // slate-*/red-*/... — в коде системно встречается bg-slate-900
      // text-white как пара ФИКСИРОВАННОГО контраста (активные/primary
      // кнопки), слепая инверсия палитры сделала бы их нечитаемыми.
      // Новые ролевые имена вместо этого — план в /плане проекта.
      colors: {
        app: "rgb(var(--color-bg-app) / <alpha-value>)",
        surface: "rgb(var(--color-bg-surface) / <alpha-value>)",
        muted: "rgb(var(--color-bg-muted) / <alpha-value>)",
        "muted-hover": "rgb(var(--color-bg-muted-hover) / <alpha-value>)",
        "muted-active": "rgb(var(--color-bg-muted-active) / <alpha-value>)",
        inset: "rgb(var(--color-bg-inset) / <alpha-value>)",
        accent: "rgb(var(--color-bg-accent) / <alpha-value>)",
        "on-accent": "rgb(var(--color-text-on-accent) / <alpha-value>)",
        primary: "rgb(var(--color-text-primary) / <alpha-value>)",
        secondary: "rgb(var(--color-text-secondary) / <alpha-value>)",
        subtle: "rgb(var(--color-text-muted) / <alpha-value>)",
        default: "rgb(var(--color-border-default) / <alpha-value>)",
        strong: "rgb(var(--color-border-strong) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        success: "rgb(var(--color-success) / <alpha-value>)",
        brand: "rgb(var(--color-brand) / <alpha-value>)",
        link: "rgb(var(--color-link) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
