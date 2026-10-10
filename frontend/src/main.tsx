import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { bootTheme, fetchTheme } from './theme'
import App from './App'

bootTheme()
fetchTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
