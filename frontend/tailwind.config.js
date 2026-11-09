/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      colors: {
        // Neutral ink scale for text and chrome. Colour is reserved for status.
        ink: {
          950: '#0f1729',
          900: '#1a2233',
          700: '#3b4558',
          600: '#556073',
          500: '#6b7588',
          400: '#8f98a8',
          300: '#c3c9d3',
          200: '#e3e7ed',
          100: '#eff2f6',
          50: '#f7f8fa',
        },
        canvas: '#f6f7f9',
        approve: { DEFAULT: '#15803d', soft: '#ecf8f0', line: '#bfe5cc', ink: '#14532d' },
        hold: { DEFAULT: '#b45309', soft: '#fdf6e7', line: '#f3d9a4', ink: '#7c3a0a' },
        reject: { DEFAULT: '#b91c1c', soft: '#fdf0f0', line: '#f3c4c4', ink: '#7f1d1d' },
        running: { DEFAULT: '#2563eb', soft: '#eef4ff', line: '#c7d8fb', ink: '#1e3a8a' },
        pending: { DEFAULT: '#8f98a8', soft: '#f3f5f8', line: '#dfe3ea' },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.04)',
        lift: '0 4px 16px -4px rgba(16, 24, 40, 0.10), 0 2px 4px -2px rgba(16, 24, 40, 0.05)',
      },
      keyframes: {
        'soft-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(37, 99, 235, 0.28)' },
          '50%': { boxShadow: '0 0 0 6px rgba(37, 99, 235, 0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'bar-slide': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(250%)' },
        },
      },
      animation: {
        'soft-pulse': 'soft-pulse 1.8s ease-in-out infinite',
        shimmer: 'shimmer 1.4s linear infinite',
        'fade-up': 'fade-up 220ms ease-out both',
        'bar-slide': 'bar-slide 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
