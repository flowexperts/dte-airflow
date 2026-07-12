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

const SEP_WIRE = "__";
const SEP_DISPLAY = ".";

function isReserved(name: string): boolean {
  return name.startsWith("_dlt_");
}

/** `order__amount` → `order.amount`. Reserved `_dlt_*` names pass through. */
export function toDisplay(wire: string): string {
  if (isReserved(wire)) return wire;
  return wire.split(SEP_WIRE).join(SEP_DISPLAY);
}

/** `order.amount` → `order__amount`. Accepts either form; idempotent. */
export function toWire(input: string): string {
  if (isReserved(input)) return input;
  if (input.includes(SEP_WIRE)) return input;
  return input.split(SEP_DISPLAY).join(SEP_WIRE);
}

export function toPath(wire: string): string[] {
  if (isReserved(wire)) return [wire];
  return wire.split(SEP_WIRE);
}

export function buildTree(
  fields: { name: string; type?: string }[],
): FieldNode[] {
  const roots: FieldNode[] = [];
  const rootIndex = new Map<string, FieldNode>();

  for (const f of fields) {
    const path = toPath(f.name);
    if (path.length === 1) {
      const existing = rootIndex.get(path[0]);
      if (existing) {
        existing.type = f.type ?? existing.type;
        existing.wire = f.name;
        continue;
      }
      const node: FieldNode = {
        name: path[0],
        wire: f.name,
        path,
        type: f.type,
      };
      roots.push(node);
      rootIndex.set(path[0], node);
      continue;
    }

    let siblings = roots;
    let index = rootIndex;
    let acc: string[] = [];
    for (let i = 0; i < path.length; i++) {
      const seg = path[i];
      acc = [...acc, seg];
      const isLeaf = i === path.length - 1;
      let node = index.get(seg);
      if (!node) {
        node = {
          name: seg,
          wire: acc.join(SEP_WIRE),
          path: acc,
        };
        if (!isLeaf) node.children = [];
        siblings.push(node);
        index.set(seg, node);
      } else if (!isLeaf && !node.children) {
        node.children = [];
      }
      if (isLeaf) {
        node.type = f.type;
        node.wire = f.name;
      } else {
        siblings = node.children!;
        const nextIndex = new Map<string, FieldNode>();
        for (const c of siblings) nextIndex.set(c.name, c);
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
