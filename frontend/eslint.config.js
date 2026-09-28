import eslint from "@eslint/js";
import vue from "eslint-plugin-vue";
import typescript from "typescript-eslint";

export default [
  { ignores: ["dist/**", "coverage/**", "node_modules/**"] },
  eslint.configs.recommended,
  ...typescript.configs.recommended,
  ...vue.configs["flat/recommended"],
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: {
        parser: typescript.parser,
      },
    },
  },
  {
    rules: {
      // Prettier owns template layout and intentionally wraps attributes differently.
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
    },
  },
];
