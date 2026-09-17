import { useTheme } from '@material-ui/core/styles';
import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubNode, useInfrahubQuery } from '../client';
import { useKindColours } from '../colours';

/**
 * The racks at a site and what is mounted in them. `rack` sits alongside a
 * device's `location` rather than replacing it, so the generator's
 * location__ids lookup keeps working.
 */
/** On a site, every rack in it; on a rack, just that one. */
export const RACK_FIELDS = `
  id
  display_label
  shortname { value }
  facility_id { value }
  height { value }
  mounted_devices {
    edges {
      node {
        id
        display_label
        position { value }
        rack_face { value }
        device_type { node { name { value } height { value } } }
      }
    }
  }
`;

const SITE_QUERY = `
  query ($id: ID!) {
    LocationRack(parent__ids: [$id]) {
      edges { node { ${RACK_FIELDS} } }
    }
  }
`;

export type RackNode = {
  id: string;
  display_label: string;
  shortname: { value: string };
  facility_id: { value: string | null };
  height: { value: number | null };
  mounted_devices: {
    edges: {
      node: {
        id: string;
        display_label: string;
        position: { value: number | null };
        rack_face: { value: string | null };
        device_type: {
          node: {
            name: { value: string };
            height: { value: number | null };
          } | null;
        } | null;
      };
    }[];
  };
};

type Racks = {
  LocationRack: {
    edges: {
      node: {
        id: string;
        display_label: string;
        shortname: { value: string };
        facility_id: { value: string | null };
        height: { value: number | null };
        mounted_devices: {
          edges: {
            node: {
              id: string;
              display_label: string;
              position: { value: number | null };
              rack_face: { value: string | null };
              device_type: {
                node: {
                  name: { value: string };
                  height: { value: number | null };
                } | null;
              } | null;
            };
          }[];
        };
      };
    }[];
  };
};

const U_HEIGHT = 22;

/** Routers and switches read differently at a glance. */
/** Routers and switches read differently at a glance. */
const colourFor = (
  colours: { device: string; deviceAlt: string },
  type?: string,
) =>
  type?.toLowerCase().includes('router') ? colours.device : colours.deviceAlt;

export function Rack(props: { rack: RackNode }) {
  const theme = useTheme();
  const colours = useKindColours();
  const units = props.rack.height.value ?? 24;
  const devices = props.rack.mounted_devices.edges
    .map(edge => edge.node)
    .filter(device => device.position.value !== null);

  return (
    <div style={{ marginRight: 32, marginBottom: 16 }}>
      <div style={{ fontWeight: 600, fontSize: 13 }}>
        {props.rack.display_label}
      </div>
      <div
        style={{
          fontSize: 11,
          opacity: 0.7,
          marginBottom: 6,
          fontFamily: 'ui-monospace, monospace',
        }}
      >
        {[props.rack.facility_id.value, `${units}U`]
          .filter(Boolean)
          .join(' · ')}
      </div>

      <div
        style={{
          position: 'relative',
          width: 232,
          height: units * U_HEIGHT,
          border: `2px solid ${theme.palette.divider}`,
          borderRadius: 4,
          background: theme.palette.background.default,
        }}
      >
        {/* U numbering runs bottom to top, the way a rack is actually counted. */}
        {Array.from({ length: units }, (_, index) => (
          <div
            key={index}
            style={{
              position: 'absolute',
              bottom: index * U_HEIGHT,
              left: 0,
              right: 0,
              height: U_HEIGHT,
              borderTop:
                index === units - 1
                  ? 'none'
                  : `1px solid ${theme.palette.divider}`,
              display: 'flex',
              alignItems: 'center',
              paddingLeft: 4,
              fontSize: 9,
              color: theme.palette.text.disabled,
              fontFamily: 'ui-monospace, monospace',
            }}
          >
            {index + 1}
          </div>
        ))}

        {devices.map(device => {
          const position = device.position.value!;
          const height = device.device_type?.node?.height.value ?? 1;
          const colour = colourFor(
            colours,
            device.device_type?.node?.name.value,
          );
          return (
            <div
              key={device.id}
              title={`${device.display_label} — U${position}${
                height > 1 ? `-${position + height - 1}` : ''
              }, ${device.rack_face.value ?? 'front'}`}
              style={{
                position: 'absolute',
                bottom: (position - 1) * U_HEIGHT + 1,
                left: 22,
                right: 4,
                height: height * U_HEIGHT - 2,
                background: colour,
                borderRadius: 3,
                color: '#fff',
                fontSize: 11,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0 8px',
                // A rear-mounted device is hatched, so both faces can share one
                // elevation without a second drawing.
                backgroundImage:
                  device.rack_face.value === 'rear'
                    ? 'repeating-linear-gradient(45deg, rgba(0,0,0,.25) 0 4px, transparent 4px 8px)'
                    : undefined,
              }}
            >
              <span>{device.display_label}</span>
              <span style={{ opacity: 0.8, fontWeight: 400 }}>
                {device.device_type?.node?.name.value?.replace('Generic ', '')}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function RackElevation() {
  const { id, kind, title } = useInfrahubNode();
  const onRack = kind === 'LocationRack';
  const { data, loading, error } = useInfrahubQuery<Racks>(
    onRack ? SITE_QUERY.replace('parent__ids', 'ids') : SITE_QUERY,
    { id },
    [id, onRack],
  );

  if (!id) {
    return <InfoCard title="Racks">No Infrahub id on this entity.</InfoCard>;
  }
  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const racks = data!.LocationRack.edges.map(edge => edge.node);
  const mounted = racks.reduce(
    (total, rack) => total + rack.mounted_devices.edges.length,
    0,
  );

  if (racks.length === 0) {
    return (
      <InfoCard title={onRack ? `Elevation: ${title}` : `Racks: ${title}`}>
        {onRack
          ? 'This rack was not found in Infrahub.'
          : 'No racks at this site yet.'}
      </InfoCard>
    );
  }

  return (
    <InfoCard
      title={onRack ? `Elevation: ${title}` : `Racks: ${title}`}
      subheader={`${racks.length} rack${
        racks.length === 1 ? '' : 's'
      }, ${mounted} devices mounted — hatched is rear-facing`}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap' }}>
        {racks.map(rack => (
          <Rack key={rack.id} rack={rack} />
        ))}
      </div>
    </InfoCard>
  );
}
