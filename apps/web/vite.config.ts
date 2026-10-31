import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    strictPort: true,
    proxy: {
      '/api': {
        target:'http://127.0.0.1:8787',changeOrigin:true,
        configure(proxy) {
          // Only rebase the exact loopback dev-server origin, never an arbitrary
          // browser Origin. The Worker retains its strict same-origin guard.
          proxy.on('proxyReq',(outgoing,incoming)=>{
            if(incoming.headers.origin==='http://127.0.0.1:5173')
              outgoing.setHeader('Origin','http://127.0.0.1:8787');
          });
        },
      },
    },
  },
  build: { sourcemap: false },
});
