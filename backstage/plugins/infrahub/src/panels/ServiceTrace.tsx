import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubNode, useInfrahubQuery } from '../client';
import { GraphEdge, GraphNode, InfrahubGraph } from './graph';

/**
 * Everything Infrahub allocated for this service, as a graph. Uses the
 * traversal API rather than the service's own fields, so it works for any
 * service kind without knowing its schema.
 */
const QUERY = `
  query ($id: String!) {
    InfrahubReachableNodes(
      data: {
        source_id: $id
        target_kinds: [
          "DcimDevice"
          "DcimInterface"
          "IpamVLAN"
          "IpamPrefix"
          "IpamIPAddress"
          "LocationSite"
        ]
        max_depth: 2
        shortest_paths_only: true
      }
    ) {
      count
      source { id kind display_label }
      dependencies {
        depth
        node { id kind display_label }
        path {
          hops {
            node { id kind display_label }
            relationship { from_label to_label }
          }
        }
      }
    }
  }
`;

type Hop = {
  node: { id: string; kind: string; display_label: string };
  relationship: { from_label?: string; to_label?: string } | null;
};

export type Reachable = {
  InfrahubReachableNodes: {
    count: number;
    source: { id: string; kind: string; display_label: string };
    dependencies: {
      depth: number;
      node: { id: string; kind: string; display_label: string };
      path: { hops: Hop[] } | null;
    }[];
  };
};

/**
 * Turns traversal paths into a graph. Pure, so the one subtle rule in here --
 * dropping anything reached through the site -- can be tested.
 */
export function buildTraceGraph(
  result: Reachable['InfrahubReachableNodes'],
  /** Where an Infrahub object of a given kind and id can be viewed. */
  objectUrl?: (kind: string, id: string) => string,
): {
  nodes: GraphNode[];
  edges: GraphEdge[];
} {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const seenEdges = new Set<string>();

  nodes.set(result.source.id, {
    id: result.source.id,
    kind: result.source.kind,
    label: result.source.display_label,
    depth: 0,
    href: objectUrl?.(result.source.kind, result.source.id),
  });

  for (const dependency of result.dependencies) {
    const hops = dependency.path?.hops ?? [];
    // A device reached through the site is every device at that site, not part
    // of this service, so only keep paths that stay on the service's own chain.
    const viaSite = hops
      .slice(0, -1)
      .some(hop => hop.node.kind.startsWith('Location'));
    if (viaSite) {
      continue;
    }

    hops.forEach((hop, index) => {
      if (!nodes.has(hop.node.id)) {
        nodes.set(hop.node.id, {
          id: hop.node.id,
          kind: hop.node.kind,
          label: hop.node.display_label,
          depth: index,
          href: objectUrl?.(hop.node.kind, hop.node.id),
        });
      }
      const previous = hops[index - 1];
      if (!previous) {
        return;
      }
      const key = `${previous.node.id}->${hop.node.id}`;
      if (seenEdges.has(key)) {
        return;
      }
      seenEdges.add(key);
      edges.push({
        from: previous.node.id,
        to: hop.node.id,
        label: hop.relationship?.to_label ?? undefined,
      });
    });
  }

  return { nodes: [...nodes.values()], edges };
}

export function ServiceTrace() {
  const { id, title, infrahubUrl } = useInfrahubNode();
  const { data, loading, error } = useInfrahubQuery<Reachable>(QUERY, { id }, [
    id,
  ]);

  if (!id) {
    return (
      <InfoCard title="Service trace">
        This entity has no Infrahub id annotation.
      </InfoCard>
    );
  }
  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const { nodes, edges } = buildTraceGraph(
    data!.InfrahubReachableNodes,
    (kind, nodeId) => `${infrahubUrl}/objects/${kind}/${nodeId}`,
  );

  return (
    <InfoCard
      title={`Service trace: ${title}`}
      subheader={`${
        nodes.length - 1
      } allocated objects, from Infrahub's graph traversal`}
    >
      <InfrahubGraph nodes={[...nodes.values()]} edges={edges} height={520} />
    </InfoCard>
  );
}
