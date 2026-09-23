import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubNode, useInfrahubQuery } from '../client';
import { GraphEdge, GraphNode, InfrahubGraph } from './graph';

/** What a site holds: the kit in it, and the services delivered from it. */
const QUERY = `
  query ($id: ID!) {
    LocationSite(ids: [$id]) {
      edges {
        node {
          id
          display_label
          devices {
            edges {
              node {
                id
                display_label
                __typename
                # A site holds DcimPhysicalDevice, but interfaces live on the
                # generic, so the port count needs a fragment.
                ... on DcimGenericDevice {
                  interfaces { count }
                }
              }
            }
          }
          services {
            edges { node { id display_label __typename } }
          }
        }
      }
    }
  }
`;

type Site = {
  LocationSite: {
    edges: {
      node: {
        id: string;
        display_label: string;
        devices: {
          edges: {
            node: {
              id: string;
              display_label: string;
              __typename: string;
              interfaces?: { count: number };
            };
          }[];
        };
        services: {
          edges: {
            node: { id: string; display_label: string; __typename: string };
          }[];
        };
      };
    }[];
  };
};

export function SiteMap() {
  const { id, title } = useInfrahubNode();
  const { data, loading, error } = useInfrahubQuery<Site>(QUERY, { id }, [id]);

  if (!id) {
    return <InfoCard title="Site map">No Infrahub id on this entity.</InfoCard>;
  }
  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const site = data!.LocationSite.edges[0]?.node;
  if (!site) {
    return <InfoCard title="Site map">Not found in Infrahub.</InfoCard>;
  }

  const devices = site.devices.edges.map(edge => edge.node);
  const services = site.services.edges.map(edge => edge.node);

  const nodes: GraphNode[] = [
    { id: site.id, kind: 'LocationSite', label: site.display_label, depth: 1 },
    ...services.map(service => ({
      id: service.id,
      kind: service.__typename,
      label: service.display_label,
      depth: 0,
    })),
    ...devices.map(device => ({
      id: device.id,
      kind: device.__typename,
      label: device.interfaces
        ? `${device.display_label} · ${device.interfaces.count} ports`
        : device.display_label,
      depth: 2,
    })),
  ];

  // Services are delivered from the site, and the kit sits in it.
  const edges: GraphEdge[] = [
    ...services.map(service => ({
      from: service.id,
      to: site.id,
      label: 'delivered from',
    })),
    ...devices.map(device => ({
      from: site.id,
      to: device.id,
      label: 'hosts',
    })),
  ];

  return (
    <InfoCard
      title={`Site map: ${title}`}
      subheader={`${services.length} services, ${devices.length} devices`}
    >
      <InfrahubGraph nodes={nodes} edges={edges} height={520} />
    </InfoCard>
  );
}
