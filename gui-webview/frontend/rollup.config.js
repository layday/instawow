import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import resolve from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import typescript from "@rollup/plugin-typescript";
import copy from "rollup-plugin-copy";
import css from "rollup-plugin-css-only";
import livereload from "rollup-plugin-livereload";
import svelte from "rollup-plugin-svelte";
import { terser } from "rollup-plugin-terser";
import sveltePreprocess from "svelte-preprocess";

const BUILD_DIR = "../src/instawow_gui/frontend";

const PRODUCTION = !process.env.ROLLUP_WATCH;

export default [
  {
    input: "src/index.ts",
    output: {
      sourcemap: !PRODUCTION,
      format: "iife",
      file: `${BUILD_DIR}/svelte-bundle.js`,
      exports: "auto",
      name: "instawow_gui",
    },
    plugins: [
      copy({
        targets: [
          {
            src: "src/index.html",
            dest: BUILD_DIR,
            transform: (c) =>
              c
                .toString()
                .replace(
                  "__csp__",
                  "script-src 'self'" + (!PRODUCTION ? " http://127.0.0.1:35729/" : "")
                ),
          },
        ],
        copyOnce: true,
      }),
      svelte({
        preprocess: sveltePreprocess({ sourceMap: !PRODUCTION }),
        compilerOptions: {
          // enable run-time checks when not in production
          dev: !PRODUCTION,
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
        sourceMap: !PRODUCTION,
        inlineSources: !PRODUCTION,
      }),
      commonjs(),
      replace({
        preventAssignment: true,
        values: { "process.env.NODE_ENV": JSON.stringify("production") },
      }),
      json(),
      !PRODUCTION && livereload(BUILD_DIR),
      PRODUCTION && terser(),
    ],
  },
];
