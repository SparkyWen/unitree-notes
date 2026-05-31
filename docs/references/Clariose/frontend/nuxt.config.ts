// Nuxt configuration for Clariose — clarity after care.
// SSR is enabled because the consultation page benefits from a fast first
// paint, while client-only sub-components handle audio capture / WebGL.

export default defineNuxtConfig({
  compatibilityDate: '2025-04-29',
  devtools: { enabled: false },

  modules: [
    '@nuxtjs/tailwindcss',
    '@vueuse/nuxt',
    '@nuxtjs/google-fonts',
  ],

  css: ['~/assets/css/main.css'],

  app: {
    head: {
      title: 'Clariose — Clarity after care.',
      htmlAttrs: { lang: 'en' },
      charset: 'utf-8',
      viewport: 'width=device-width, initial-scale=1',
      meta: [
        {
          name: 'description',
          content:
            'Clariose is a calm AI health companion. Live consultation transcripts, gentle reminders, and family-friendly summaries — clarity after care.',
        },
        { name: 'theme-color', content: '#F7F2EC' },
        { property: 'og:title', content: 'Clariose — Clarity after care.' },
        {
          property: 'og:description',
          content:
            'A quiet companion that turns every consultation into a clear, actionable record.',
        },
        { property: 'og:type', content: 'website' },
        { property: 'og:url', content: 'https://zai.gold' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      ],
    },
  },

  googleFonts: {
    families: {
      Inter: [300, 400, 500, 600, 700],
      Fraunces: [400, '400i', 500, '500i', 600],
      'Space Grotesk': [400, 500, 600, 700],
      'JetBrains Mono': [400, 500],
    },
    display: 'swap',
    preload: true,
  },

  tailwindcss: {
    configPath: 'tailwind.config.ts',
  },

  // Default to SSR; the /carenote sub-tree is client-only because it owns
  // microphone capture and per-visit live state.
  ssr: true,
  routeRules: {
    '/carenote/**': { ssr: false },
    // Recall console uses EventSource SSE + clipboard + drag-drop upload.
    '/recall/**': { ssr: false },
  },

  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api',
      siteName: 'Clariose',
    },
  },

  nitro: {
    preset: 'node-server',
    // dev only: Nuxt's dev server proxies /api → dev backend so the browser
    // always speaks same-origin, regardless of how the dev FE is reached
    // (SSH tunnel, port-forward, localhost). Prod is unaffected — nginx
    // handles /api in prod and devProxy is ignored by the built server.
    devProxy: {
      '/api': {
        target: 'http://127.0.0.1:4401/api',
        changeOrigin: true,
      },
    },
  },

  experimental: {
    payloadExtraction: false,
  },
});
