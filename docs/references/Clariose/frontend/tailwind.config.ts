import type { Config } from 'tailwindcss';

/**
 * Clariose — clarity + rose.
 *
 * Warm ivory canvas, near-black ink, dusty-rose primary, calm sage healing,
 * champagne tonal. Editorial, refined, premium AI health companion.
 */
export default <Partial<Config>>{
  content: [
    './components/**/*.{vue,js,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './composables/**/*.ts',
    './plugins/**/*.{js,ts}',
    './app.vue',
    './error.vue',
  ],
  theme: {
    extend: {
      fontFamily: {
        // Editorial serif used in hero headlines & numerals.
        // Fraunces — warm, wide, modern serif with proper italics.
        display: ['Fraunces', 'Georgia', '"Times New Roman"', 'serif'],
        // Workhorse sans for everything else.
        sans: ['Inter', 'system-ui', 'sans-serif'],
        // Wordmark + numeric stat displays.
        grotesk: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
        // Tabular figures, code, technical labels.
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        // Warm ivory canvas → near-black ink.
        canvas: '#F7F2EC',
        paper: '#FFFFFF',
        ink: {
          50: '#FAF7F2',
          100: '#EFEAE0',
          200: '#D9D2C4',
          300: '#B5AC9C',
          400: '#8A8275',
          500: '#5C544D',
          600: '#3F3934',
          700: '#26221F',
          800: '#161310',
          900: '#0B0907',
          950: '#050403',
        },
        line: {
          DEFAULT: 'rgba(11,9,7,0.10)',
          soft: 'rgba(11,9,7,0.06)',
          strong: 'rgba(11,9,7,0.18)',
        },
        // Dusty rose — Clariose primary. Soft, refined, warm.
        clay: {
          50:  '#FBF1F1',
          100: '#F5DCDD',
          200: '#EAB7BB',
          300: '#DA8E94',
          400: '#C76C75',
          500: '#B85065',
          600: '#963F52',
          700: '#71303F',
          800: '#4D202B',
          900: '#2C121A',
        },
        // Rose alias (same scale, clearer naming for new code).
        rose: {
          50:  '#FBF1F1',
          100: '#F5DCDD',
          200: '#EAB7BB',
          300: '#DA8E94',
          400: '#C76C75',
          500: '#B85065',
          600: '#963F52',
          700: '#71303F',
          800: '#4D202B',
          900: '#2C121A',
        },
        // Calm sage healing accent.
        sage: {
          50:  '#F1F4EE',
          100: '#E0E7D9',
          200: '#C2CFB5',
          300: '#9DB089',
          400: '#7C9268',
          500: '#5F7A4E',
          600: '#48613B',
          700: '#374A2D',
          800: '#283621',
          900: '#1A2316',
        },
        // Champagne tonal — premium warm.
        champagne: {
          50:  '#FBF6EC',
          100: '#F2E8D2',
          200: '#E5D2A5',
          300: '#D4B776',
          400: '#B8954B',
          500: '#8E6F2D',
        },
        // Soft amber — risk / watch.
        amber: {
          50:  '#FBF6E9',
          100: '#F5E9C4',
          200: '#EBD382',
          300: '#DBB544',
          400: '#BB951E',
          500: '#947214',
          600: '#6E550E',
        },
      },
      letterSpacing: {
        'tightest-2': '-0.04em',
        editorial: '-0.02em',
      },
      boxShadow: {
        hairline: '0 0 0 1px rgba(11,9,7,0.08)',
        card: '0 1px 0 rgba(11,9,7,0.04), 0 12px 28px -16px rgba(11,9,7,0.18)',
        lifted: '0 1px 0 rgba(11,9,7,0.04), 0 24px 60px -28px rgba(11,9,7,0.28)',
        glow: '0 24px 80px -32px rgba(184,80,101,0.45)',
        focus: '0 0 0 3px rgba(184,80,101,0.20)',
      },
      borderRadius: {
        '4xl': '2rem',
        '5xl': '2.5rem',
      },
      backgroundImage: {
        'rose-bloom':
          'radial-gradient(120% 80% at 50% 0%, rgba(184,80,101,0.10), rgba(184,80,101,0) 60%)',
        'sage-bloom':
          'radial-gradient(120% 80% at 0% 100%, rgba(95,122,78,0.10), rgba(95,122,78,0) 60%)',
        'grain-light':
          "url(\"data:image/svg+xml;utf8,<svg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.45'/></svg>\")",
      },
      keyframes: {
        rise: {
          '0%':   { opacity: '0', transform: 'translateY(14px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        ringPulse: {
          '0%':   { transform: 'scale(0.6)', opacity: '0.55' },
          '100%': { transform: 'scale(2.0)', opacity: '0' },
        },
        breathe: {
          '0%, 100%': { transform: 'scale(1)',    opacity: '0.85' },
          '50%':      { transform: 'scale(1.04)', opacity: '1' },
        },
        marquee: {
          '0%':   { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        bloom: {
          '0%, 100%': { transform: 'scale(1) rotate(0deg)',   opacity: '0.7' },
          '50%':      { transform: 'scale(1.08) rotate(2deg)', opacity: '1' },
        },
      },
      animation: {
        rise: 'rise 700ms cubic-bezier(0.22, 1, 0.36, 1) both',
        'ring-pulse': 'ringPulse 2.4s ease-out infinite',
        breathe: 'breathe 5s ease-in-out infinite',
        marquee: 'marquee 40s linear infinite',
        bloom: 'bloom 9s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
