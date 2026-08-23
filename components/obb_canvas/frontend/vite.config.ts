import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Streamlit Community Cloud serves this component's frontend/build/ directory as static
// files verbatim - it never runs `npm install`/`npm run build` itself, so the build output
// is committed to git. `base: "./"` uses relative asset paths since the iframe is served
// from a Streamlit-controlled path, not a known absolute origin.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../build',
    emptyOutDir: true,
  },
})
