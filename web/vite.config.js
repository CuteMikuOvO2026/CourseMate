import { defineConfig } from 'vite';

export default defineConfig({
  // 不使用 @vitejs/plugin-react：esbuild 的 automatic JSX 已足够，
  // 且可避开该插件与 Vite 7 的版本冲突。
  esbuild: { jsx: 'automatic' },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
