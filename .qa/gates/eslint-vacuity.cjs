/**
 * G3 vacuity rules for JS/TS test files (spec §5 G3).
 *
 * The spec is explicit: implement G3 as a lint rule per language, not as a
 * bespoke cross-language AST tool. These are stock rules from
 * eslint-plugin-vitest (swap for eslint-plugin-jest if the repo uses jest).
 *
 * Install: npm i -D eslint eslint-plugin-vitest @typescript-eslint/parser
 */
module.exports = {
  root: true,
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["vitest"],
  rules: {
    // zero assertions — the test proves only that nothing threw
    "vitest/expect-expect": ["error", {
      assertFunctionNames: ["expect", "assert", "request.**.expect"],
    }],
    // skip / only / todo are not evidence
    "vitest/no-disabled-tests": "error",
    "vitest/no-focused-tests": "error",
    // an assertion inside a conditional may never run
    "vitest/no-conditional-expect": "error",
    // expect() with no matcher attached
    "vitest/valid-expect": "error",
    "vitest/no-standalone-expect": "error",
    // identical titles hide silently-overwritten tests
    "vitest/no-identical-title": "error",
  },
};
