/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#1A1A2E',
          light: '#24243E',
        },
        accent: {
          DEFAULT: '#EC4899',
          light: '#F472B6',
          dim: 'rgba(236, 72, 153, 0.2)',
        },
        violet: {
          neon: '#8B5CF6',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 20px rgba(236, 72, 153, 0.3)',
        'glow-violet': '0 0 20px rgba(139, 92, 246, 0.3)',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
