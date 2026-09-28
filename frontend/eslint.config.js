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
      globals: {
        DragEvent: "readonly",
        Event: "readonly",
        File: "readonly",
        HTMLInputElement: "readonly",
      },
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
      "vue/html-closing-bracket-newline": "off",
      "vue/html-indent": "off",
      "vue/html-self-closing": "off",
      "vue/multiline-html-element-content-newline": "off",
    },
  },
];
