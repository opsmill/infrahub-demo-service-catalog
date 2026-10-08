import { addressesIn, cellRole } from './PrefixMap';
import { buildTraceGraph, Reachable } from './ServiceTrace';
import { capacity, RackOption, withSelected } from '../pages/RacksPage';
import { roleFor } from './graph';

describe('addressesIn', () => {
  it('expands a /29 into its eight addresses', () => {
    expect(addressesIn('203.0.113.8/29')?.addresses).toEqual([
      '203.0.113.8',
      '203.0.113.9',
      '203.0.113.10',
      '203.0.113.11',
      '203.0.113.12',
      '203.0.113.13',
      '203.0.113.14',
      '203.0.113.15',
    ]);
  });

  it('carries across an octet boundary', () => {
    const block = addressesIn('10.0.0.254/30');
    expect(block?.addresses).toEqual([
      '10.0.0.254',
      '10.0.0.255',
      '10.0.1.0',
      '10.0.1.1',
    ]);
  });

  it('handles the top of the address space without overflowing', () => {
    expect(addressesIn('255.255.255.252/30')?.addresses).toEqual([
      '255.255.255.252',
      '255.255.255.253',
      '255.255.255.254',
      '255.255.255.255',
    ]);
  });

  it('refuses a block too large to draw', () => {
    expect(addressesIn('10.0.0.0/8')).toBeUndefined();
  });

  it('refuses what it cannot parse, including IPv6', () => {
    expect(addressesIn('2001:db8::/64')).toBeUndefined();
    expect(addressesIn('not-a-prefix')).toBeUndefined();
    expect(addressesIn('203.0.113.0')).toBeUndefined();
  });
});

describe('cellRole', () => {
  it('marks an assigned address, and prefers that over reserved', () => {
    expect(
      cellRole({ assigned: true, isNetwork: true, isBroadcast: false }),
    ).toBe('assigned');
  });

  it('names the network and broadcast addresses', () => {
    expect(
      cellRole({ assigned: false, isNetwork: true, isBroadcast: false }),
    ).toBe('network address');
    expect(
      cellRole({ assigned: false, isNetwork: false, isBroadcast: true }),
    ).toBe('broadcast address');
  });

  it('leaves everything else free', () => {
    expect(
      cellRole({ assigned: false, isNetwork: false, isBroadcast: false }),
    ).toBe('free');
  });
});

describe('withSelected', () => {
  const option = (id: string): RackOption => ({
    id,
    shortname: { value: id },
    display_label: id,
    parent: null,
  });

  it('pins the selected rack when a search has excluded it', () => {
    // Otherwise the picker blanks mid-search and MUI drops the value.
    expect(
      withSelected([option('dal01-ra')], option('bru01-ra')).map(o => o.id),
    ).toEqual(['bru01-ra', 'dal01-ra']);
  });

  it('leaves the options alone when the selection is already there', () => {
    const options = [option('bru01-ra'), option('dal01-ra')];

    expect(withSelected(options, option('bru01-ra'))).toBe(options);
  });

  it('leaves the options alone when nothing is selected', () => {
    const options = [option('bru01-ra')];

    expect(withSelected(options, null)).toBe(options);
  });
});

describe('capacity', () => {
  const rack = (units: number, heights: (number | null)[]) =>
    ({
      height: { value: units },
      mounted_devices: {
        edges: heights.map(height => ({
          node: { device_type: { node: { height: { value: height } } } },
        })),
      },
    } as any);

  it('counts used units from device heights, not device count', () => {
    expect(capacity(rack(24, [1, 2, 4]))).toEqual({
      units: 24,
      used: 7,
      free: 17,
    });
  });

  it('assumes 1U for a device whose type has no height', () => {
    expect(capacity(rack(10, [null, null])).used).toBe(2);
  });

  it('never reports negative free space in an over-filled rack', () => {
    expect(capacity(rack(2, [4])).free).toBe(0);
  });
});

describe('buildTraceGraph', () => {
  const hop = (id: string, kind: string, label = id) => ({
    node: { id, kind, display_label: label },
    relationship: { to_label: 'Service' },
  });

  const result = (
    dependencies: Reachable['InfrahubReachableNodes']['dependencies'],
  ): Reachable['InfrahubReachableNodes'] => ({
    count: dependencies.length,
    source: {
      id: 'svc',
      kind: 'ServiceDedicatedInternet',
      display_label: 'int-001',
    },
    dependencies,
  });

  it('always includes the service itself as the root', () => {
    const { nodes } = buildTraceGraph(result([]));
    expect(nodes).toEqual([
      {
        id: 'svc',
        kind: 'ServiceDedicatedInternet',
        label: 'int-001',
        depth: 0,
      },
    ]);
  });

  it('links every node back to its Infrahub object when told how', () => {
    const { nodes } = buildTraceGraph(
      result([
        {
          depth: 1,
          node: { id: 'dev', kind: 'DcimDevice', display_label: 'sw01' },
          path: {
            hops: [
              hop('svc', 'ServiceDedicatedInternet', 'int-001'),
              hop('dev', 'DcimDevice', 'sw01'),
            ],
          },
        },
      ]),
      (kind, nodeId) => `https://infrahub.test/objects/${kind}/${nodeId}`,
    );

    expect(nodes.map(node => node.href)).toEqual([
      'https://infrahub.test/objects/ServiceDedicatedInternet/svc',
      'https://infrahub.test/objects/DcimDevice/dev',
    ]);
  });

  it('keeps a device reached through the service own interface', () => {
    const { nodes, edges } = buildTraceGraph(
      result([
        {
          depth: 2,
          node: { id: 'dev', kind: 'DcimDevice', display_label: 'sw01' },
          path: {
            hops: [
              hop('svc', 'ServiceDedicatedInternet', 'int-001'),
              hop('if', 'DcimInterfaceL2', 'Ethernet4'),
              hop('dev', 'DcimDevice', 'sw01'),
            ],
          },
        },
      ]),
    );

    expect(nodes.map(n => n.label)).toEqual(['int-001', 'Ethernet4', 'sw01']);
    expect(edges).toEqual([
      { from: 'svc', to: 'if', label: 'Service' },
      { from: 'if', to: 'dev', label: 'Service' },
    ]);
  });

  it('drops a device reached through the site, which is every device there', () => {
    const { nodes } = buildTraceGraph(
      result([
        {
          depth: 2,
          node: { id: 'other', kind: 'DcimDevice', display_label: 'rb99' },
          path: {
            hops: [
              hop('svc', 'ServiceDedicatedInternet', 'int-001'),
              hop('site', 'LocationSite', 'Brussels 1'),
              hop('other', 'DcimDevice', 'rb99'),
            ],
          },
        },
      ]),
    );

    expect(nodes.map(n => n.label)).not.toContain('rb99');
  });

  it('keeps the site itself, which is the last hop of its own path', () => {
    const { nodes } = buildTraceGraph(
      result([
        {
          depth: 1,
          node: {
            id: 'site',
            kind: 'LocationSite',
            display_label: 'Brussels 1',
          },
          path: {
            hops: [
              hop('svc', 'ServiceDedicatedInternet', 'int-001'),
              hop('site', 'LocationSite', 'Brussels 1'),
            ],
          },
        },
      ]),
    );

    expect(nodes.map(n => n.label)).toContain('Brussels 1');
  });

  it('does not duplicate a node or an edge two paths share', () => {
    const shared = {
      depth: 2,
      node: { id: 'dev', kind: 'DcimDevice', display_label: 'sw01' },
      path: {
        hops: [
          hop('svc', 'ServiceDedicatedInternet', 'int-001'),
          hop('if', 'DcimInterfaceL2', 'Ethernet4'),
          hop('dev', 'DcimDevice', 'sw01'),
        ],
      },
    };
    const { nodes, edges } = buildTraceGraph(result([shared, shared]));

    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);
  });

  it('tolerates a dependency with no path', () => {
    expect(() =>
      buildTraceGraph(
        result([
          {
            depth: 1,
            node: { id: 'x', kind: 'IpamPrefix', display_label: 'p' },
            path: null,
          },
        ]),
      ),
    ).not.toThrow();
  });
});

describe('roleFor', () => {
  it('groups kinds by Infrahub namespace', () => {
    expect(roleFor('ServiceDedicatedInternet')).toBe(
      roleFor('ServiceWireless'),
    );
    expect(roleFor('DcimDevice')).not.toBe(roleFor('IpamPrefix'));
  });

  it('falls back for an unknown namespace rather than returning undefined', () => {
    expect(roleFor('SomethingNew')).toBe('neutral');
  });
});
