import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // 3D visualization dependencies are intentionally lazy-loaded into a large async chunk.
    chunkSizeWarningLimit: 1300,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('react-force-graph-2d') || id.includes('force-graph/src') || id.includes('/d3-')) {
            return 'graph-2d'
          }
          if (id.includes('react-force-graph-3d') || id.includes('3d-force-graph') || id.includes('three-spritetext') || id.includes('/three/')) {
            return 'graph-3d'
          }
          if (id.includes('/node_modules/react') || id.includes('/node_modules/react-dom')) {
            return 'react-vendor'
          }
          if (id.includes('/node_modules/lucide-react')) {
            return 'icons'
          }
          return undefined
        },
      },
    },
  },
})
