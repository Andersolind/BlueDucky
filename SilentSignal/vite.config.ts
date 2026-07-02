import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// Mic capture (getUserMedia) needs a secure context. On localhost that's already
// satisfied, but to use the mic from another device over your LAN you must serve
// HTTPS. Run `npm run dev:https` (sets HTTPS=1) to enable a self-signed cert —
// the browser will warn once; accept it and the mic works over the network URL.
// https://vite.dev/config/
export default defineConfig(() => {
  const https = process.env.HTTPS === '1'
  return {
    plugins: [react(), ...(https ? [basicSsl()] : [])],
    server: {
      host: true,
      port: 5173,
    },
  }
})
