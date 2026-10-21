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
        "brand-soft": "rgb(var(--color-brand-soft) / <alpha-value>)",
        "brand-text": "rgb(var(--color-brand-text) / <alpha-value>)",
        link: "rgb(var(--color-link) / <alpha-value>)",
        "danger-soft": "rgb(var(--color-danger-soft) / <alpha-value>)",
        "success-soft": "rgb(var(--color-success-soft) / <alpha-value>)",
        lime: "rgb(var(--color-lime) / <alpha-value>)",
        "on-lime": "rgb(var(--color-on-lime) / <alpha-value>)",
        nav: "rgb(var(--color-nav) / <alpha-value>)",
        "nav-text": "rgb(var(--color-nav-text) / <alpha-value>)",
        "nav-muted": "rgb(var(--color-nav-muted) / <alpha-value>)",
      },
      // Редизайн 21.10: шрифт и скругления из макетов. Шкала радиусов
      // переопределена целиком, а не точечно: "rounded" стоит в сотнях
      // мест, и переписывать каждое ради 10px вместо 4px бессмысленно —
      // новый вид должен прийти одним изменением шкалы.
      fontFamily: {
        sans: ['"Manrope Variable"', "system-ui", "-apple-system", '"Segoe UI"', "Roboto", "sans-serif"],
      },
      borderRadius: {
        sm: "6px",
        DEFAULT: "10px",
        md: "12px",
        lg: "16px",
        xl: "20px",
        "2xl": "24px",
        "3xl": "28px",
      },
      boxShadow: {
        card: "0 1px 0 rgb(var(--color-border-default))",
        float: "0 6px 18px rgb(var(--color-text-primary) / 0.06), 0 1px 0 rgb(var(--color-border-default))",
        nav: "0 12px 30px rgb(0 0 0 / 0.3)",
      },
      // Реальный найденный баг: голый класс "border" (без цвета следом) по
      // умолчанию в Tailwind не наследует currentColor, как можно
      // подумать — borderColor.DEFAULT в стоковой теме жёстко указывает
      // на theme('colors.gray.200') (см. node_modules/tailwindcss/stubs/
      // config.full.js), и это ЗНАЧЕНИЕ (светло-серый) никак не зависело
      // от темы приложения. По всему коду десятки мест используют именно
      // голый "border" — все они рендерились одинаковым светлым
      // #e5e7eb даже в тёмной теме, отсюда "все кнопки явно светлым
      // обведены". Явно указываем DEFAULT на свой токен.
      borderColor: {
        DEFAULT: "rgb(var(--color-border-default) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
