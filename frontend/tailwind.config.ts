import type { Config } from 'tailwindcss'
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: Object.fromEntries(
        [
          'border',
          'input',
          'ring',
          'background',
          'foreground',
          'primary',
          'secondary',
          'destructive',
          'muted',
          'accent',
          'card',
        ].map((name) => [
          name,
          { DEFAULT: `hsl(var(--${name}))`, foreground: `hsl(var(--${name}-foreground))` },
        ])
      ),
      fontFamily: {
        sans: ['"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['Consolas', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
