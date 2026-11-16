import { N_, t } from '#lib/i18n.svelte.ts';

// The server sends a relationship as a stable kind (`parent-of`); the words are the catalogue's.
// A bare label names the kind in a list; a statement is the whole sentence, with both people,
// so each language puts the pair in the order and case it needs.
const LABELS: Record<string, string> = {
  'partner-of': N_('partner of'),
  'spouse-of': N_('married to'),
  'parent-of': N_('parent of'),
  'mother-of': N_('mother of'),
  'father-of': N_('father of'),
  'child-of': N_('child of'),
  'son-of': N_('son of'),
  'daughter-of': N_('daughter of'),
  'sibling-of': N_('sibling of'),
  'sister-of': N_('sister of'),
  'brother-of': N_('brother of'),
  'twin-of': N_('twin of'),
  'godparent-of': N_('godparent of'),
  'godmother-of': N_('godmother of'),
  'godfather-of': N_('godfather of'),
  'godchild-of': N_('godchild of'),
  'best-friend-of': N_('best friend of'),
  'friend-of': N_('friend of'),
  'uncle-of': N_('uncle of'),
  'aunt-of': N_('aunt of'),
  'aunt-or-uncle-of': N_('aunt or uncle of'),
  'nibling-of': N_('niece or nephew of'),
  'cousin-of': N_('cousin of'),
  'grandparent-of': N_('grandparent of'),
  'grandchild-of': N_('grandchild of'),
  'parent-in-law-of': N_('parent-in-law of'),
  'child-in-law-of': N_('child-in-law of'),
  'sibling-in-law-of': N_('sibling-in-law of'),
};

const STATEMENTS: Record<string, string> = {
  'partner-of': N_("{a} is {b}'s partner"),
  'spouse-of': N_("{a} is {b}'s spouse"),
  'parent-of': N_("{a} is {b}'s parent"),
  'mother-of': N_("{a} is {b}'s mother"),
  'father-of': N_("{a} is {b}'s father"),
  'child-of': N_("{a} is {b}'s child"),
  'son-of': N_("{a} is {b}'s son"),
  'daughter-of': N_("{a} is {b}'s daughter"),
  'sibling-of': N_("{a} is {b}'s sibling"),
  'sister-of': N_("{a} is {b}'s sister"),
  'brother-of': N_("{a} is {b}'s brother"),
  'twin-of': N_("{a} is {b}'s twin"),
  'godparent-of': N_("{a} is {b}'s godparent"),
  'godmother-of': N_("{a} is {b}'s godmother"),
  'godfather-of': N_("{a} is {b}'s godfather"),
  'godchild-of': N_("{a} is {b}'s godchild"),
  'best-friend-of': N_("{a} is {b}'s best friend"),
  'friend-of': N_("{a} is {b}'s friend"),
  'uncle-of': N_("{a} is {b}'s uncle"),
  'aunt-of': N_("{a} is {b}'s aunt"),
  'aunt-or-uncle-of': N_("{a} is {b}'s aunt or uncle"),
  'nibling-of': N_("{a} is {b}'s niece or nephew"),
  'cousin-of': N_("{a} is {b}'s cousin"),
  'grandparent-of': N_("{a} is {b}'s grandparent"),
  'grandchild-of': N_("{a} is {b}'s grandchild"),
  'parent-in-law-of': N_("{a} is {b}'s parent-in-law"),
  'child-in-law-of': N_("{a} is {b}'s child-in-law"),
  'sibling-in-law-of': N_("{a} is {b}'s sibling-in-law"),
};

/** The kind as a list entry ("parent"); a kind this client does not know shows as its own name. */
export const kindLabel = (kind: string) => (LABELS[kind] ? t(LABELS[kind]) : kind.replaceAll('-', ' '));

/** "{a} is {b}'s parent", in the reader's language and word order. */
export const kindStatement = (kind: string, a: string, b: string) =>
  STATEMENTS[kind] ? t(STATEMENTS[kind], { a, b }) : `${a} ${kind.replaceAll('-', ' ')} ${b}`;

// Why the scan or the owner linked a pair; a reason this client does not know shows as sent.
const VIA: Record<string, string> = {
  'co-occurrence': N_('often in the same pictures'),
  'birth-date': N_('same birth date'),
  name: N_('same name'),
  you: N_('you said so'),
};

export const viaLabel = (via: string) => (VIA[via] ? t(VIA[via]) : via);

/** A suggestion's chain, one statement per step ("Gran is Bob's parent; Bob is Riley's parent"). */
export const chainStatement = (steps: { person: string; kind: string; other: string }[]) =>
  steps
    .map((step) => kindStatement(step.kind, step.person, step.other))
    .reduce((so_far, next) => t('{first}; {second}', { first: so_far, second: next }));
