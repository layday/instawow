const path = require("node:path");

module.exports = {
  env: {
    browser: true,
    es2020: true,
  },
  extends: ["eslint:recommended"],
  overrides: [
    {
      files: ["*.svelte"],
      parser: "svelte-eslint-parser",
      // Parse the `<script>` in `.svelte` as TypeScript by adding the following configuration.
      parserOptions: {
        parser: {
          ts: "@typescript-eslint/parser",
        },
      },
      extends: ["plugin:@typescript-eslint/recommended", "plugin:svelte/recommended"],
      rules: {
        "@typescript-eslint/await-thenable": "error",
      },
    },
    {
      files: ["*.ts"],
      parser: "@typescript-eslint/parser",
      extends: ["plugin:@typescript-eslint/recommended"],
      rules: {
        "@typescript-eslint/await-thenable": "error",
      },
    },
  ],
  parserOptions: {
    project: path.resolve(__dirname, "tsconfig.json"),
    extraFileExtensions: [".svelte"],
  },
  plugins: ["@typescript-eslint"],
  root: true,
};
