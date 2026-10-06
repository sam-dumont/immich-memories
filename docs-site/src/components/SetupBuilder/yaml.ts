// A small block-style YAML writer for the plain data the setup builder emits:
// maps, lists, strings, numbers, booleans and null. Anything a YAML parser could
// read as something other than a string is double-quoted, so a value never changes type.

export class Block {
  text: string;
  constructor(text: string) {
    this.text = text;
  }
}

// Letters, digits and a few separators, starting with a letter: never a number, a
// date, an anchor, a tag, a flow collection, a comment or a `key: value` pair.
const PLAIN = /^[A-Za-z_][A-Za-z0-9_./-]*$/;
const RESERVED = /^(?:true|false|yes|no|on|off|y|n|null)$/i;

function scalar(value: string): string {
  return PLAIN.test(value) && !RESERVED.test(value) ? value : JSON.stringify(value).replace(/[\u0085\u2028\u2029]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

function emit(value: unknown, indent: number): string[] {
  const pad = ' '.repeat(indent);
  if (Array.isArray(value)) {
    if (!value.length) return [`${pad}[]`];
    return value.flatMap(item => {
      const inner = emit(item, indent + 2);
      if (isCollection(item) && !isEmpty(item)) {
        return [`${pad}- ${inner[0].slice(indent + 2)}`, ...inner.slice(1)];
      }
      return [`${pad}- ${inner[0].trim()}`, ...inner.slice(1)];
    });
  }
  if (value && typeof value === 'object' && !(value instanceof Block)) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) return [`${pad}{}`];
    return entries.flatMap(([key, item]) => {
      const name = scalar(key);
      if (item instanceof Block) {
        const lines = item.text.replace(/\n$/, '').split('\n');
        return [`${pad}${name}: |`, ...lines.map(line => (line ? `${pad}  ${line}` : ''))];
      }
      if (isCollection(item) && !isEmpty(item)) return [`${pad}${name}:`, ...emit(item, indent + 2)];
      return [`${pad}${name}: ${emit(item, 0)[0]}`];
    });
  }
  if (value === null || value === undefined) return [`${pad}null`];
  if (typeof value === 'string') return [`${pad}${scalar(value)}`];
  if (typeof value === 'number' && Number.isFinite(value)) return [`${pad}${value}`];
  if (typeof value === 'boolean') return [`${pad}${value}`];
  throw new TypeError(`Cannot write ${typeof value} as YAML.`);
}

const isCollection = (value: unknown): boolean =>
  Boolean(value) && typeof value === 'object' && !(value instanceof Block);
const isEmpty = (value: unknown): boolean =>
  Array.isArray(value) ? !value.length : Object.keys(value as object).length === 0;

export function toYaml(value: unknown): string {
  return emit(value, 0).join('\n');
}

// The same tree with each Block turned back into its text.
export function plain(value: unknown): unknown {
  if (value instanceof Block) return value.text;
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, plain(item)]));
  }
  return value;
}
