import type { components } from '#lib/api-types.ts';

export type FamilyTree = components['schemas']['FamilyTree'];
type TreePerson = components['schemas']['TreePerson'];

// The server places people in person widths and rows; the drawing turns those into pixels.
const UNIT = 136;
const ROW = 196;
const PAD_X = 76;
const PAD_TOP = 64;
export const FACE = 30;
// Where a family's line to its children runs, above the children's faces.
const BUS = 54;

export type Node = TreePerson & { cx: number; cy: number; initials: string };
export type Line = { d: string; dashed: boolean; testid: string };
export type Knot = { x: number; y: number; dashed: boolean };
export type Dotted = { source: Node; target: Node; kind: string; d: string; button: { x: number; y: number } };

export type Drawing = { width: number; height: number; nodes: Node[]; lines: Line[]; knots: Knot[]; dotted: Dotted[] };

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('');

const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;

/** Pixels for every person, couple, family line and suggestion of a laid-out tree. */
export function draw(tree: FamilyTree): Drawing {
  const nodes = tree.people.map((p) => ({ ...p, cx: PAD_X + p.x * UNIT, cy: PAD_TOP + p.generation * ROW, initials: initials(p.name) }));
  const at = new Map(nodes.map((node) => [node.person_id, node]));
  const lines: Line[] = [];
  const knots: Knot[] = [];

  for (const [a, b] of tree.couples) {
    const [left, right] = [at.get(a), at.get(b)].sort((m, n) => (m?.cx ?? 0) - (n?.cx ?? 0));
    if (left && right) lines.push({ d: `M${left.cx + FACE},${left.cy}H${right.cx - FACE}`, dashed: false, testid: 'tree-couple' });
  }

  for (const family of tree.families) {
    const parents = family.parents.flatMap((id) => at.get(id) ?? []);
    const children = family.children.flatMap((child) => {
      const node = at.get(child.person_id);
      return node ? [{ node, dashed: child.through_sibling }] : [];
    });
    if (!children.length) continue;
    const busY = Math.min(...children.map((c) => c.node.cy)) - BUS;
    const knot: Knot = !parents.length
      ? { x: mean(children.map((c) => c.node.cx)), y: busY - 22, dashed: true }
      : parents.length === 1
        ? { x: parents[0].cx, y: parents[0].cy + FACE + 44, dashed: false }
        : { x: mean(parents.map((p) => p.cx)), y: mean(parents.map((p) => p.cy)), dashed: false };
    knots.push(knot);
    const xs = [knot.x, ...children.map((c) => c.node.cx)];
    lines.push({ d: `M${knot.x},${knot.y}V${busY}M${Math.min(...xs)},${busY}H${Math.max(...xs)}`, dashed: knot.dashed, testid: 'tree-family' });
    for (const child of children) {
      lines.push({ d: `M${child.node.cx},${busY}V${child.node.cy - FACE}`, dashed: child.dashed, testid: 'tree-child' });
    }
  }

  const dotted = tree.suggestions.flatMap((s) => {
    const source = at.get(s.source);
    const target = at.get(s.target);
    if (!source || !target) return [];
    // Same row: bow above the faces so the line doesn't run through the people between.
    const bow = source.cy === target.cy ? 70 : 0;
    const control = { x: (source.cx + target.cx) / 2, y: (source.cy + target.cy) / 2 - bow };
    const button = { x: (source.cx + 2 * control.x + target.cx) / 4, y: (source.cy + 2 * control.y + target.cy) / 4 };
    return [{ source, target, kind: s.kind, d: `M${source.cx},${source.cy}Q${control.x},${control.y} ${target.cx},${target.cy}`, button }];
  });

  const width = Math.ceil(Math.max(0, ...nodes.map((n) => n.cx)) + PAD_X);
  const height = Math.ceil(Math.max(0, ...nodes.map((n) => n.cy)) + FACE + 52);
  return { width, height, nodes, lines, knots, dotted };
}
