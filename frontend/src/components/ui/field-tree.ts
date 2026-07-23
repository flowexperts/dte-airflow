export interface FieldNode {
  name: string;
  wire: string;
  path: string[];
  type?: string;
  children?: FieldNode[];
}

export interface FieldRef {
  wire: string;
  display: string;
  path: string[];
}

const SEP = ".";

function isReserved(name: string): boolean {
  return name.startsWith("_dlt_");
}

/** Wire form is now dot syntax — matches STRUCT paths. Identity + guard. */
export function toDisplay(wire: string): string {
  return wire;
}

/** Accepts either dot form or legacy `__`-flat; normalises to dot. Idempotent. */
export function toWire(input: string): string {
  if (isReserved(input)) return input;
  if (input.includes(SEP)) return input;
  return input.split("__").join(SEP);
}

export function toPath(wire: string): string[] {
  if (isReserved(wire)) return [wire];
  return wire.split(SEP);
}

interface FieldInput {
  name: string;
  type?: string;
  children?: FieldInput[] | null;
}

/** Build the tree.
 *
 * The backend now returns `SchemaField[]` with an optional `children` array
 * for STRUCT columns — we walk it directly. As a fallback, a flat list of
 * dot-form leaves (or legacy `__`-flat names) is still supported by
 * splitting on the separator and building a trie.
 */
export function buildTree(fields: FieldInput[]): FieldNode[] {
  // If the input carries `children`, treat it as an already-shaped tree.
  const isTree = fields.some((f) => Array.isArray(f.children));
  if (isTree) {
    const walk = (
      nodes: FieldInput[],
      parent: string[] = [],
    ): FieldNode[] =>
      nodes.map((n) => {
        const path = [...parent, n.name];
        const wire = path.join(SEP);
        if (Array.isArray(n.children) && n.children.length) {
          return {
            name: n.name,
            wire,
            path,
            type: n.type,
            children: walk(n.children, path),
          };
        }
        return { name: n.name, wire, path, type: n.type };
      });
    return walk(fields);
  }

  // Fallback: flat list → trie.
  const roots: FieldNode[] = [];
  const rootIndex = new Map<string, FieldNode>();
  for (const f of fields) {
    const path = toPath(f.name);
    let siblings = roots;
    let index = rootIndex;
    let acc: string[] = [];
    for (let i = 0; i < path.length; i++) {
      const seg = path[i];
      if (seg === undefined) continue;
      acc = [...acc, seg];
      const isLeaf = i === path.length - 1;
      let node = index.get(seg);
      if (!node) {
        node = { name: seg, wire: acc.join(SEP), path: acc };
        if (!isLeaf) node.children = [];
        siblings.push(node);
        index.set(seg, node);
      } else if (!isLeaf && !node.children) {
        node.children = [];
      }
      if (isLeaf) {
        node.type = f.type;
        node.wire = acc.join(SEP);
      } else {
        const kids = node.children ?? (node.children = []);
        siblings = kids;
        const nextIndex = new Map<string, FieldNode>();
        for (const c of kids) nextIndex.set(c.name, c);
        index = nextIndex;
      }
    }
  }
  return roots;
}

export function findNode(tree: FieldNode[], wire: string): FieldNode | null {
  for (const node of tree) {
    if (node.wire === wire) return node;
    if (node.children) {
      const hit = findNode(node.children, wire);
      if (hit) return hit;
    }
  }
  return null;
}

export function collectLeaves(nodes: FieldNode[]): FieldNode[] {
  const out: FieldNode[] = [];
  const walk = (arr: FieldNode[]) => {
    for (const n of arr) {
      if (n.children && n.children.length) walk(n.children);
      else out.push(n);
    }
  };
  walk(nodes);
  return out;
}
