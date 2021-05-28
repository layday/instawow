import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import resolve from "@rollup/plugin-node-resolve";
import svelte from "rollup-plugin-svelte";
import typescript from "@rollup/plugin-typescript";
import css from "rollup-plugin-css-only";
import sveltePreprocess from "svelte-preprocess";

const production = !process.env.ROLLUP_WATCH;

export default [
  {
    input: "src/index.ts",
    output: {
      sourcemap: true,
      format: "iife",
      file: "../src/instawow_gui/frontend/svelte-bundle.js",
      exports: "auto",
    },
    plugins: [
      svelte({
        preprocess: sveltePreprocess({ sourceMap: !production }),
        compilerOptions: {
          // enable run-time checks when not in production
          dev: !production,
        },
      }),
      // we'll extract any component CSS out into
      // a separate file - better for performance
      css({ output: "svelte-bundle.css" }),
      // If you have external dependencies installed from
      // npm, you'll most likely need these plugins. In
      // some cases you'll need additional configuration -
      // consult the documentation for details:
      // https://github.com/rollup/plugins/tree/master/packages/commonjs
      resolve({
        browser: true,
        dedupe: ["svelte"],
        preferBuiltins: false,
      }),
      typescript({
        sourceMap: !production,
        inlineSources: !production,
      }),
      commonjs(),
      json(),
    ],
    watch: {
      clearScreen: false,
    },
  },
];
