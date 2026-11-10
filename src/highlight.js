const keywords = new Set("and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield".split(" "));
const constants = new Set(["True", "False", "None"]);
const builtins = new Set(["print", "range", "len", "int", "float", "str", "bool", "enumerate", "zip", "sum", "min", "max", "abs", "wait_for", "wait_until"]);
const pairs = { ")": "(", "]": "[", "}": "{" };

export function highlightPython(code, target) {
  const fragment = document.createDocumentFragment();
  const stack = [];
  let plain = "";
  let i = 0;

  function flush() {
    if (plain) fragment.append(document.createTextNode(plain));
    plain = "";
  }

  function token(value, kind) {
    flush();
    const span = document.createElement("span");
    span.className = `tok-${kind}`;
    span.textContent = value;
    fragment.append(span);
  }

  function quoted(start, quoteAt) {
    const quote = code[quoteAt];
    const triple = code.slice(quoteAt, quoteAt + 3) === quote.repeat(3);
    const width = triple ? 3 : 1;
    let end = quoteAt + width;
    while (end < code.length) {
      if (code[end] === "\\") { end += 2; continue; }
      if (code.slice(end, end + width) === quote.repeat(width)) { end += width; break; }
      if (!triple && code[end] === "\n") break;
      end++;
    }
    token(code.slice(start, end), "string");
    i = end;
  }

  while (i < code.length) {
    const ch = code[i];
    if (ch === "#") {
      const end = code.indexOf("\n", i);
      const next = end < 0 ? code.length : end;
      token(code.slice(i, next), "comment");
      i = next;
    } else if (ch === "'" || ch === '"') {
      quoted(i, i);
    } else if (/[A-Za-z_]/.test(ch)) {
      const start = i++;
      while (i < code.length && /\w/.test(code[i])) i++;
      const word = code.slice(start, i);
      if (/^[rfbu]{1,3}$/i.test(word) && (code[i] === "'" || code[i] === '"')) {
        quoted(start, i);
      } else {
        const kind = keywords.has(word) ? "keyword" : constants.has(word) ? "constant" : builtins.has(word) || (code[i] === "(" && code[start - 1] === ".") ? "function" : "";
        if (kind) token(word, kind);
        else plain += word;
      }
    } else if (/\d/.test(ch)) {
      const match = code.slice(i).match(/^(?:0[xX][\da-fA-F]+|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/);
      token(match[0], "number");
      i += match[0].length;
    } else if (ch === "(" || ch === "[" || ch === "{") {
      token(ch, `bracket-${stack.length % 3}`);
      stack.push(ch);
      i++;
    } else if (ch === ")" || ch === "]" || ch === "}") {
      const matching = stack.at(-1) === pairs[ch];
      token(ch, matching ? `bracket-${(stack.length - 1) % 3}` : "bracket-error");
      if (matching) stack.pop();
      i++;
    } else if (/[+\-*\/%=<>!&|^~:]/.test(ch)) {
      const start = i++;
      while (i < code.length && /[+\-*\/%=<>!&|^~:]/.test(code[i])) i++;
      token(code.slice(start, i), "operator");
    } else {
      plain += ch;
      i++;
    }
  }
  plain += code.endsWith("\n") ? " " : "";
  flush();
  target.replaceChildren(fragment);
}
