import { useTheme } from '@material-ui/core/styles';
import {
  Background,
  Edge,
  MarkerType,
  Node,
  Position,
  ReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useKindColours } from '../colours';

/**
 * Which role an Infrahub kind plays, decided by its namespace prefix. Kept
 * separate from the colours themselves so the classification stays pure --
 * the colours come from the theme, this does not.
 */
const ROLE_BY_PREFIX = {
  Service: 'service',
  Dcim: 'device',
  Ipam: 'address',
  Location: 'place',
  Core: 'neutral',
} as const;

export type KindRole = (typeof ROLE_BY_PREFIX)[keyof typeof ROLE_BY_PREFIX];

/** One role per Infrahub namespace, so a graph reads at a glance. */
export function roleFor(kind: string): KindRole {
  const prefix = Object.keys(ROLE_BY_PREFIX).find(candidate =>
    kind.startsWith(candidate),
  ) as keyof typeof ROLE_BY_PREFIX | undefined;

  return prefix ? ROLE_BY_PREFIX[prefix] : 'neutral';
}

export type GraphNode = {
  id: string;
  kind: string;
  label: string;
  /** Column, so the layout reads left to right by distance from the source. */
  depth: number;
  /** Where clicking the node goes. Without it the graph is only a picture. */
  href?: string;
};

export type GraphEdge = { from: string; to: string; label?: string };

/**
 * Lays nodes out in columns by depth and rows within a column. Deliberately not
 * a force layout: these graphs are small and a stable, readable arrangement
 * beats one that moves every time it loads.
 */
export function InfrahubGraph(props: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
}) {
  const byId = new Map(props.nodes.map(node => [node.id, node]));
  // Read the colours off the Backstage theme, so the graph is legible in both
  // light and dark rather than a white box with white text in one of them.
  const theme = useTheme();
  const colours = useKindColours();
  const columns = new Map<number, GraphNode[]>();
  for (const node of props.nodes) {
    columns.set(node.depth, [...(columns.get(node.depth) ?? []), node]);
  }

  const tallest = Math.max(...[...columns.values()].map(c => c.length), 1);

  const flowNodes: Node[] = props.nodes.map(node => {
    const column = columns.get(node.depth)!;
    const row = column.indexOf(node);
    // Centre each column vertically against the tallest one.
    const offset = (tallest - column.length) / 2;
    return {
      id: node.id,
      position: { x: node.depth * 240, y: (row + offset) * 78 },
      data: {
        label: (
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontSize: 11, opacity: 0.7 }}>{node.kind}</div>
            <div style={{ fontWeight: 600 }}>{node.label}</div>
          </div>
        ),
      },
      style: {
        border: `2px solid ${colours[roleFor(node.kind)]}`,
        borderRadius: 6,
        padding: '6px 10px',
        background: theme.palette.background.paper,
        color: theme.palette.text.primary,
        width: 200,
        fontSize: 13,
        cursor: node.href ? 'pointer' : 'default',
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
  });

  const flowEdges: Edge[] = props.edges.map((edge, index) => ({
    id: `${edge.from}-${edge.to}-${index}`,
    source: edge.from,
    target: edge.to,
    label: edge.label,
    labelStyle: { fontSize: 10, fill: theme.palette.text.secondary },
    labelBgStyle: { fill: theme.palette.background.paper },
    style: { stroke: theme.palette.divider },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));

  return (
    <div style={{ height: props.height ?? 460 }}>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        fitView
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_event, node) => {
          const href = byId.get(node.id)?.href;
          if (href) {
            // A new tab: the graph is usually a step in a longer investigation.
            window.open(href, '_blank', 'noopener,noreferrer');
          }
        }}
      >
        <Background color={theme.palette.divider} />
      </ReactFlow>
    </div>
  );
}
