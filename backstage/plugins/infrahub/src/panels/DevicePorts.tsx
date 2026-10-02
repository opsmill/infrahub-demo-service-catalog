import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubNode, useInfrahubQuery } from '../client';
import { useKindColours, useStatusColours } from '../colours';

const QUERY = `
  query ($id: ID!) {
    DcimGenericDevice(ids: [$id]) {
      edges {
        node {
          display_label
          interfaces {
            edges {
              node {
                id
                display_label
                ... on DcimInterface {
                  status { value }
                  role { value }
                  speed { value }
                  enabled { value }
                  service { node { display_label } }
                }
              }
            }
          }
        }
      }
    }
  }
`;

type Ports = {
  DcimGenericDevice: {
    edges: {
      node: {
        display_label: string;
        interfaces: {
          edges: {
            node: {
              id: string;
              display_label: string;
              status?: { value: string | null };
              role?: { value: string | null };
              speed?: { value: number | null };
              enabled?: { value: boolean | null };
              service?: { node: { display_label: string } | null } | null;
            };
          }[];
        };
      };
    }[];
  };
};

/** Port colours follow the interface status, the thing an operator scans for. */
/** Port colours follow the interface status, the thing an operator scans for. */
const statusColours = (status: {
  ok: string;
  idle: string;
  pending: string;
  error: string;
}): Record<string, string> => ({
  active: status.ok,
  free: status.idle,
  provisioning: status.pending,
  maintenance: status.pending,
  drained: status.error,
});

const speedLabel = (mbps?: number | null) => {
  if (!mbps) return '';
  return mbps >= 1000 ? `${mbps / 1000}G` : `${mbps}M`;
};

export function DevicePorts() {
  const colours = useKindColours();
  const byStatus = statusColours(useStatusColours());
  const { id, title } = useInfrahubNode();
  const { data, loading, error } = useInfrahubQuery<Ports>(QUERY, { id }, [id]);

  if (!id) {
    return <InfoCard title="Ports">No Infrahub id on this entity.</InfoCard>;
  }
  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const device = data!.DcimGenericDevice.edges[0]?.node;
  if (!device) {
    return <InfoCard title="Ports">Not found in Infrahub.</InfoCard>;
  }

  const ports = device.interfaces.edges.map(edge => edge.node);
  const used = ports.filter(p => p.status?.value === 'active').length;

  return (
    <InfoCard
      title={`Ports: ${title}`}
      subheader={`${used} of ${ports.length} active`}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(148px, 1fr))',
          gap: 8,
        }}
      >
        {ports.map(port => {
          const status = port.status?.value ?? 'unknown';
          const colour = byStatus[status] ?? colours.neutral;
          return (
            <div
              key={port.id}
              title={`${status}${
                port.service?.node
                  ? ` — ${port.service.node.display_label}`
                  : ''
              }`}
              style={{
                border: `1px solid ${colour}`,
                // A filled left edge reads as a status light on a patch panel.
                borderLeft: `6px solid ${colour}`,
                borderRadius: 4,
                padding: '6px 8px',
                opacity: port.enabled?.value === false ? 0.45 : 1,
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13 }}>
                {port.display_label}
              </div>
              <div style={{ fontSize: 11, opacity: 0.75 }}>
                {[port.role?.value, speedLabel(port.speed?.value), status]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
              {port.service?.node && (
                <div style={{ fontSize: 11, color: colour, fontWeight: 600 }}>
                  {port.service.node.display_label}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </InfoCard>
  );
}
