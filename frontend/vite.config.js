import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { SITE_NAME, SITE_SHORT } from './src/site.js'

// index.html says the site's name as %SITE_NAME% (src/site.js is the one place it's set).
const siteName = { name: 'site-name', transformIndexHtml: html => html.replaceAll('%SITE_NAME%', SITE_NAME) }

export default defineConfig({
  plugins: [
    react(),
    siteName,
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['apple-touch-icon.png'],
      manifest: {
        name: SITE_NAME,
        short_name: SITE_SHORT,
        description: 'Arthouse & repertory showtimes for the club',
        theme_color: '#1f070c',
        background_color: '#1f070c',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Web push (R8d): public/push-sw.js shows alerts and opens their page.
        importScripts: ['push-sw.js'],
        // Page loads under /api/ (Sign in with Discord and its callback) must
        // reach the server; by default the service worker answers every page
        // load with the cached app, which bounced Discord sign-in back to "/".
        navigateFallbackDenylist: [/^\/api\//, /^\/sitemap\.xml$/, /^\/robots\.txt$/],
        // API responses are never stored by the service worker (R7b): its
        // 5-second give-up left pages empty when the server was slow, and it
        // kept signed-in data on the device. The site keeps what it loaded in
        // memory instead (src/api.js).
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/image\.tmdb\.org\//,
            handler: 'CacheFirst',
            options: {
              cacheName: 'tmdb-images',
              expiration: { maxEntries: 300, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5001',
    },
  },
})
