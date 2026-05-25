/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef5ff',
          100: '#d9e8ff',
          200: '#bcd7ff',
          300: '#8ebeff',
          400: '#599bff',
          500: '#3377ff',
          600: '#1a55f5',
          700: '#1340e1',
          800: '#1635b6',
          900: '#18308f',
          950: '#141f57',
        },
        surface: {
          50: '#f8f9fb',
          100: '#f0f1f5',
          200: '#e4e6ed',
          300: '#d0d3de',
          400: '#a8adc0',
          500: '#8389a1',
          600: '#6b7089',
          700: '#575c70',
          800: '#4a4d5e',
          900: '#404350',
          950: '#1e1f27',
        },
      },
      fontFamily: {
        display: ['"Source Sans 3"', 'system-ui', 'sans-serif'],
        body: ['"Source Sans 3"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
