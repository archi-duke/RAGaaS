import { createRoot } from 'react-dom/client'
import '@progress/kendo-theme-bootstrap/dist/all.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <App />
)
