/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50:  '#eef2ff',
          100: '#e0e7ff',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
        },
        sidebar: {
          bg:     '#1e1b4b',
          hover:  '#2d2a5e',
          active: '#3730a3',
          text:   '#c7d2fe',
        },
      },
    },
  },
  plugins: [],
}
