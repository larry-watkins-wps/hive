import type { Config } from 'tailwindcss';
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { hive: { bg: '#080814', panel: '#0d0d18', ink: '#e8e8f0' } } } },
  plugins: [],
} satisfies Config;
