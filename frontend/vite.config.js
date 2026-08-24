import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(async ({ command, mode }) => {
  const isProduction = mode === 'production'
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_BASE_URL || 'http://localhost:8000'

  const plugins = [vue()]

  if (isProduction) {
    try {
      const { default: ob } = await import('vite-plugin-javascript-obfuscator')
      plugins.push(
        ob({
          include: [/src\/services\/.*\.js$/, /src\/views\/admin\/.*\.vue$/],
          compact: true,
          controlFlowFlattening: true,
          controlFlowFlatteningThreshold: 0.5,
          stringArray: true,
          stringArrayEncoding: ['rc4'],
          stringArrayThreshold: 0.5,
          renameGlobals: true,
          deadCodeInjection: false,
          debugProtection: false,
          disableConsoleOutput: false,
        }),
      )
    } catch {
      console.warn('vite-plugin-javascript-obfuscator not available, skipping obfuscation')
    }
  }

  return {
    plugins,
    build: {
      sourcemap: false,
      minify: isProduction ? 'terser' : 'esbuild',
      rollupOptions: {
        output: {
          entryFileNames: 'assets/[name]-[hash].js',
          chunkFileNames: 'assets/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
      },
      terserOptions: isProduction
        ? {
            compress: {
              drop_console: true,
              drop_debugger: true,
            },
          }
        : {},
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/docs': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/openapi.json': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
