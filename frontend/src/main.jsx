import './legacyLinks'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import './ui/ui.css'

import ErrorBoundary from './ui/ErrorBoundary'

// The old service worker's stored API responses (R7b): no longer used, and
// they could hold signed-in data — remove them.
if ('caches' in window) caches.delete('api').catch(() => {})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
window.__appStarted = true          // tells index.html's start-up check the app is running
