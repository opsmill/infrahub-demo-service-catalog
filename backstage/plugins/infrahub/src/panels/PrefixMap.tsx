import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubNode, useInfrahubQuery } from '../client';
import { useKindColours, useStatusColours } from '../colours';

/** The prefix and addresses this service holds, found by traversal. */
const QUERY = `
  query ($id: String!) {
    InfrahubReachableNodes(
      data: {
        source_id: $id
        target_kinds: ["IpamPrefix", "IpamIPAddress"]
        max_depth: 1
        shortest_paths_only: true
      }
    ) {
      dependencies { node { id kind display_label } }
    }
  }
`;

type Reachable = {
  InfrahubReachableNodes: {
    dependencies: {
      node: { id: string; kind: string; display_label: string };
    }[];
  };
};

/** Every address in a v4 prefix, so the block can be drawn cell by cell. */
export function addressesIn(
  cidr: string,
): { addresses: string[]; bits: number } | undefined {
  const [network, length] = cidr.split('/');
  const bits = Number(length);
  const octets = network.split('.').map(Number);
  if (octets.length !== 4 || octets.some(isNaN) || isNaN(bits) || bits < 22) {
    // Anything larger than a /22 is too many cells to be worth drawing.
    return undefined;
  }
  const base =
    ((octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]) >>>
    0;
  const size = 2 ** (32 - bits);
  const addresses = Array.from({ length: size }, (_, index) => {
    const value = (base + index) >>> 0;
    return [24, 16, 8, 0].map(shift => (value >>> shift) & 255).join('.');
  });
  return { addresses, bits };
}

/**
 * What a single address cell means. Only the meaning -- how it reads is the
 * component's business, because the colours come from the theme.
 */
export type CellRole =
  | 'assigned'
  | 'network address'
  | 'broadcast address'
  | 'free';

export function cellRole(state: {
  assigned: boolean;
  isNetwork: boolean;
  isBroadcast: boolean;
}): CellRole {
  // An assigned address is assigned whatever else it is.
  if (state.assigned) {
    return 'assigned';
  }
  if (state.isNetwork) {
    return 'network address';
  }
  if (state.isBroadcast) {
    return 'broadcast address';
  }
  return 'free';
}

/**
 * How a cell reads. The two addresses nobody can be given are shown as
 * unavailable rather than free, which is why 'free' and reserved differ.
 */
function cellStyle(role: CellRole, assigned: string, reserved: string) {
  switch (role) {
    case 'assigned':
      return { background: assigned, color: '#fff', fontWeight: 600 };
    case 'free':
      return { background: 'transparent', color: 'inherit', fontWeight: 400 };
    default:
      return {
        background: reserved,
        color: 'inherit',
        fontWeight: 400,
        opacity: 0.6,
      };
  }
}

export function PrefixMap() {
  const colours = useKindColours();
  const status = useStatusColours();
  const { id, title } = useInfrahubNode();
  const { data, loading, error } = useInfrahubQuery<Reachable>(QUERY, { id }, [
    id,
  ]);

  if (!id) {
    return (
      <InfoCard title="IP allocation">No Infrahub id on this entity.</InfoCard>
    );
  }
  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const found = data!.InfrahubReachableNodes.dependencies.map(d => d.node);
  const prefix = found.find(node => node.kind === 'IpamPrefix');
  const held = new Set(
    found
      .filter(node => node.kind === 'IpamIPAddress')
      .map(node => node.display_label.split('/')[0]),
  );

  if (!prefix) {
    return (
      <InfoCard title="IP allocation" subheader={title}>
        No prefix allocated yet. A request gets its addresses when the generator
        runs.
      </InfoCard>
    );
  }

  const block = addressesIn(prefix.display_label);

  return (
    <InfoCard
      title="IP allocation"
      subheader={`${prefix.display_label} — ${held.size} address${
        held.size === 1 ? '' : 'es'
      } assigned`}
    >
      {!block ? (
        <div>{prefix.display_label} is too large to draw.</div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(104px, 1fr))',
            gap: 4,
          }}
        >
          {block.addresses.map((address, index) => {
            const assigned = held.has(address);
            const isNetwork = index === 0;
            const isBroadcast = index === block.addresses.length - 1;
            const role = cellRole({ assigned, isNetwork, isBroadcast });
            const paint = cellStyle(role, colours.address, status.idle);
            return (
              <div
                key={address}
                title={role}
                style={{
                  padding: '4px 6px',
                  borderRadius: 3,
                  fontSize: 11,
                  fontFamily: 'ui-monospace, monospace',
                  textAlign: 'center',
                  border: `1px solid ${status.idle}`,
                  ...paint,
                }}
              >
                {address}
              </div>
            );
          })}
        </div>
      )}
    </InfoCard>
  );
}
