import fs from "fs";
import commonjs from "@rollup/plugin-commonjs";
import resolve from "@rollup/plugin-node-resolve";
import svelte from "rollup-plugin-svelte";
import { terser } from "rollup-plugin-terser";
import typescript from "@rollup/plugin-typescript";
import autoPreprocess from "svelte-preprocess";

const production = !process.env.ROLLUP_WATCH;

function copyFile({ src, dest }) {
  return {
    name: "copyFile",
    buildEnd: () => fs.copyFileSync(src, dest),
  };
}

export default [
  {
    input: "src/backend/index.ts",
    output: {
      sourcemap: true,
      format: "cjs",
      file: "build/index.js",
    },
    plugins: [typescript(), commonjs()],
  },
  {
    input: "src/index.ts",
    output: {
      sourcemap: true,
      format: "cjs",
      file: "build/svelte-bundle.js",
      exports: "auto",
    },
    plugins: [
      svelte({
        // enable run-time checks when not in production
        dev: !production,
        preprocess: autoPreprocess(),
        // we'll extract any component CSS out into
        // a separate file - better for performance
        css: (css) => {
          css.write("svelte-bundle.css");
        },
      }),
      // If you have external dependencies installed from
      // npm, you'll most likely need these plugins. In
      // some cases you'll need additional configuration -
      // consult the documentation for details:
      // https://github.com/rollup/plugins/tree/master/packages/commonjs
      resolve({
        browser: true,
        dedupe: ["svelte"],
      }),
      typescript(),
      commonjs(),
      // In dev mode, call `npm run start` once
      // the bundle has been generated
      // !production && serve(),
      // Watch the `public` directory and refresh the
      // browser on changes when not in production
      // !production && livereload("public"),
      // If we're building for production (npm run build
      // instead of npm run dev), minify
      // production && terser(),
      copyFile({ src: "src/backend/index.html", dest: "build/index.html" }),
    ],
    external: ["electron", "fs", "path"],
    watch: {
      clearScreen: false,
    },
  },
];
