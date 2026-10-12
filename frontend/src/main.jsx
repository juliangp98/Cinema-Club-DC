import './legacyLinks'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import './ui/ui.css'

import ErrorBoundary from './ui/ErrorBoundary'
// Every stylesheet loads up front (R9e): pages load on demand, but their
// styles are shared across pages, and all of it is only ~16 kB compressed.
import "./pages/Calendar.css";
import "./pages/Club.css";
import "./pages/DiscoverPage.css";
import "./pages/FilmPage.css";
import "./pages/Polls.css";
import "./pages/Theatres.css";

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
