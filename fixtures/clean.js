// the word `pivotal` is mentioned, not used
const a = "serves as the entry point // not a comment";
const b = 'I hope this helps /* not a comment */';
const c = `// pivotal ${a + "// pivotal"} — I hope this helps`;
const r = /\/\/ pivotal "/g;
const d = a / 2; // see https://example.com/pivotal
