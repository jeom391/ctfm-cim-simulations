import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
// loadEnv (not process.env) keeps this file type-checkable without @types/node.
export default defineConfig(({ mode }) => ({ plugins: [react()], server: { proxy: { '/api': loadEnv(mode, '.', 'CTFM_').CTFM_API_URL || 'http://127.0.0.1:8000' } } }));
