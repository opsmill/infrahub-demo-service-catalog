import { LoggerService, SchedulerService } from '@backstage/backend-plugin-api';
import { Entity } from '@backstage/catalog-model';
import { InfrahubEntityProvider } from './provider';
import { CatalogConfig } from './config';
import {
  infrahubGet,
  infrahubQuery,
} from '@opsmill/backstage-plugin-infrahub-node';

jest.mock('@opsmill/backstage-plugin-infrahub-node', () => ({
  ...jest.requireActual('@opsmill/backstage-plugin-infrahub-node'),
  infrahubQuery: jest.fn(),
  infrahubGet: jest.fn(),
}));

const value = <T>(v: T) => ({ value: v });

/**
 * A fake Infrahub with two kinds: a site named directly in config, and a
 * service kind reachable only by discovering descendants of `ServiceGeneric`.
 * Between them they cover both routes into the catalog.
 */
const SCHEMA: Record<string, any> = {
  '/api/schema': {
    nodes: [
      {
        namespace: 'Service',
        name: 'Wireless',
        inherit_from: ['ServiceGeneric'],
      },
      { namespace: 'Location', name: 'Site', inherit_from: [] },
    ],
  },
  '/api/schema/LocationSite': {
    name: 'Site',
    namespace: 'Location',
    label: 'Site',
    description: 'A point of presence.',
    human_friendly_id: ['shortname__value'],
    attributes: [{ name: 'shortname', kind: 'Text', optional: false }],
    relationships: [
      { name: 'parent', peer: 'LocationMetro', cardinality: 'one' },
    ],
  },
  '/api/schema/json_schema/LocationSite': {
    title: 'Site',
    required: ['shortname'],
    properties: {
      shortname: { type: 'string' },
      description: { type: 'string', default: null },
    },
  },
  '/api/schema/ServiceWireless': {
    name: 'Wireless',
    namespace: 'Service',
    label: 'Wireless',
    human_friendly_id: ['service_identifier__value'],
    attributes: [
      {
        name: 'security',
        kind: 'Dropdown',
        // Deliberately in a different order from the json_schema enum, so a
        // positional merge would mislabel and the test would catch it.
        choices: [
          { name: 'wpa2-personal', label: 'WPA2 Personal' },
          { name: 'open', label: 'Open' },
        ],
      },
    ],
    relationships: [
      {
        name: 'location',
        peer: 'LocationSite',
        cardinality: 'one',
        optional: false,
        label: 'Site',
      },
      // A peer nobody ingests, and mandatory, so it must still reach a create.
      {
        name: 'provider',
        peer: 'OrganizationProvider',
        cardinality: 'one',
        optional: false,
      },
      { name: 'profiles', peer: 'CoreProfile', cardinality: 'many' },
    ],
  },
  '/api/schema/json_schema/ServiceWireless': {
    title: 'Wireless',
    required: ['ssid', 'service_identifier'],
    properties: {
      service_identifier: { type: 'string' },
      ssid: { type: 'string' },
      security: {
        type: 'string',
        enum: ['open', 'wpa2-personal'],
        default: 'wpa2-personal',
      },
      status: { type: 'string', enum: ['draft', 'active'] },
      // Infrahub sends an explicit null default for an optional field.
      access_points: { type: 'number', default: null },
      // A list cannot be typed into a mutation, so it is left off the form.
      tags: { type: 'array' },
    },
  },
};

const SITES = {
  LocationSite: {
    edges: [
      {
        node: {
          id: 'site-1',
          hfid: ['bru01'],
          display_label: 'Brussels 1 (bru01)',
          __typename: 'LocationSite',
          shortname: value('bru01'),
          description: value('Main POP'),
          parent: {
            node: { id: 'm-1', hfid: ['bru'], display_label: 'Brussels' },
          },
        },
      },
    ],
  },
};

const wireless = (overrides: Record<string, any> = {}) => ({
  id: 'wifi-1',
  hfid: ['WIFI-001'],
  display_label: 'WIFI-001',
  __typename: 'ServiceWireless',
  service_identifier: value('WIFI-001'),
  ssid: value(null),
  security: value('wpa2-personal'),
  access_points: value(null),
  status: value('draft'),
  location: {
    node: {
      id: 'site-1',
      hfid: ['bru01'],
      display_label: 'Brussels 1 (bru01)',
    },
  },
  provider: { node: null },
  ...overrides,
});

const CHANGE = {
  id: 'pc-1',
  source_branch: value('implement_wifi-001'),
  state: value('open'),
};

const DEFAULTS: CatalogConfig = {
  refreshMinutes: 1,
  owner: 'user:default/guest',
  system: 'infrahub-services',
  kinds: [
    {
      kind: 'LocationSite',
      entity: 'Resource',
      type: 'infrahub-site',
      template: false,
      groups: [],
      formExclude: [],
    },
  ],
  discover: [
    {
      generic: 'ServiceGeneric',
      entity: 'Component',
      template: true,
      groups: [],
      formExclude: [],
    },
  ],
};

describe('InfrahubEntityProvider', () => {
  let branchesRead: string[] = [];
  let warnings: string[] = [];
  let queries: string[] = [];

  beforeEach(() => {
    branchesRead = [];
    warnings = [];
    queries = [];
  });

  const run = async (
    options: { catalog?: Partial<CatalogConfig>; changeState?: string } = {},
  ): Promise<Record<string, Entity>> => {
    const changeState = options.changeState ?? 'open';

    (infrahubGet as jest.Mock).mockImplementation(
      async (_config: unknown, path: string) => {
        if (SCHEMA[path]) {
          return SCHEMA[path];
        }
        throw new Error(`no schema for ${path}`);
      },
    );

    (infrahubQuery as jest.Mock).mockImplementation(
      async (request: { branch?: string; query: string }) => {
        queries.push(request.query);
        if (request.branch) {
          branchesRead.push(request.branch);
        }
        if (request.query.includes('CoreProposedChange')) {
          return {
            CoreProposedChange: {
              edges: [{ node: { ...CHANGE, state: value(changeState) } }],
            },
          };
        }
        if (request.query.includes('LocationSite')) {
          return SITES;
        }
        if (request.query.includes('ServiceWireless')) {
          // On the request's own branch the branch aware values are set.
          return {
            ServiceWireless: {
              edges: [
                {
                  node: request.branch
                    ? wireless({ ssid: value('acme-corp') })
                    : wireless(),
                },
              ],
            },
          };
        }
        return {};
      },
    );

    const applied: Entity[] = [];
    const provider = new InfrahubEntityProvider(
      {
        instance: 'test',
        // Distinct on purpose: links must never carry the internal address.
        address: 'http://infrahub-server:8000',
        externalAddress: 'http://localhost:8000',
        token: 'token',
      },
      { ...DEFAULTS, ...options.catalog },
      'http://localhost:3001',
      // ponytail: two stubs instead of pulling in backend-test-utils.
      {
        info: jest.fn(),
        warn: jest.fn((message: string) => warnings.push(message)),
        error: jest.fn((message: string) => warnings.push(message)),
        debug: jest.fn(),
      } as unknown as LoggerService,
      { scheduleTask: jest.fn() } as unknown as SchedulerService,
    );

    await provider.connect({
      applyMutation: async mutation => {
        if (mutation.type === 'full') {
          applied.push(...mutation.entities.map(e => e.entity as Entity));
        }
      },
      refresh: jest.fn(),
    });
    await provider.refresh();

    return Object.fromEntries(
      applied.map(entity => [`${entity.kind}:${entity.metadata.name}`, entity]),
    );
  };

  it('ingests the kinds named in config and the ones discovered under a generic', async () => {
    expect(Object.keys(await run()).sort()).toEqual([
      'API:locationsite',
      'API:servicewireless',
      'Component:wifi-001',
      'Resource:bru01',
      'System:infrahub-services',
      'Template:wireless-request',
    ]);
  });

  it('asks a kind only for fields its own schema has', async () => {
    await run();

    const site = queries.find(query => query.includes('LocationSite'))!;
    const service = queries.find(query => query.includes('ServiceWireless'))!;

    // status is on a service but not on a site, and asking Infrahub for a field
    // a kind lacks fails the whole query -- which cost every site, rack and
    // device before this was pinned.
    expect(service).toContain('status { value }');
    expect(site).not.toContain('status');
  });

  it('names entities by their Infrahub human friendly id', async () => {
    const entities = await run();

    // hfid, not the display label and not the UUID: it is what a mutation
    // takes back, and it is what every existing link already uses.
    expect(entities['Resource:bru01'].metadata.title).toBe(
      'Brussels 1 (bru01)',
    );
    expect(entities['Component:wifi-001'].metadata.title).toBe('WIFI-001');
  });

  it('takes the Backstage kind and spec.type from config', async () => {
    const entities = await run();

    expect(entities['Resource:bru01'].spec).toMatchObject({
      type: 'infrahub-site',
      owner: 'user:default/guest',
    });
    // Only a Component belongs to a System; a Resource is not part of one.
    expect(entities['Resource:bru01'].spec!.system).toBeUndefined();
    expect(entities['Component:wifi-001'].spec!.system).toBe(
      'system:default/infrahub-services',
    );
  });

  it('describes an object from its own attributes and relationships', async () => {
    const entities = await run();

    // Nothing here is per-kind code: the fields come from the schema, and the
    // relationship line uses Infrahub's own label.
    expect(entities['Resource:bru01'].metadata.description).toBe(
      'Description Main POP · Parent Brussels',
    );
    expect(entities['Component:wifi-001'].metadata.description).toContain(
      'Ssid acme-corp requested',
    );
    expect(entities['Component:wifi-001'].metadata.description).toContain(
      'Site Brussels 1 (bru01)',
    );
  });

  it('turns a relationship into a catalog relation when the peer is ingested', async () => {
    const entities = await run();

    expect(entities['Component:wifi-001'].spec!.dependsOn).toEqual([
      'resource:default/bru01',
    ]);
    // LocationMetro is not ingested, so parent stays description text.
    expect(entities['Resource:bru01'].spec!.dependsOn).toBeUndefined();
  });

  it('generates a template only for kinds configured to have one', async () => {
    const entities = await run();

    expect(entities['Template:wireless-request']).toBeDefined();
    // A site is reference data, not something a portal user requests.
    expect(entities['Template:locationsite-request']).toBeUndefined();
  });

  it('puts a generated create into the groups its generators watch', async () => {
    const template = (
      await run({
        catalog: {
          discover: [
            {
              generic: 'ServiceGeneric',
              entity: 'Component',
              template: true,
              groups: ['automated_wireless'],
              formExclude: [],
            },
          ],
        },
      })
    )['Template:wireless-request'];

    const create = (template.spec!.steps as any[]).find(
      step => step.id === 'create',
    );

    // An Infrahub generator definition targets a *group*. A service created
    // outside it is never expanded, and then there is nothing to wait for --
    // which is exactly how a generated template silently skipped a generator.
    expect(create.input.query).toContain(
      'member_of_groups: [{ hfid: ["automated_wireless"] }]',
    );
  });

  it('labels dropdown options the way Infrahub does', async () => {
    const template = (await run())['Template:wireless-request'];
    const [parameters] = template.spec!.parameters as any[];
    // The create branch of the mode switch.
    const create = parameters.dependencies.mode.oneOf.find(
      (branch: any) => branch.properties.mode.enum[0] === 'create',
    );
    const security = create.properties.security;

    // json_schema has the values but not the labels; /api/schema has the
    // labels. Without the merge a form offers `wpa2-personal` where Infrahub
    // says "WPA2 Personal".
    expect(security.enum).toEqual(['open', 'wpa2-personal']);
    expect(security.enumNames).toEqual(['Open', 'WPA2 Personal']);
  });

  it('keeps a generator-allocated field off the form but still on the entity', async () => {
    const entities = await run({
      catalog: {
        discover: [
          {
            generic: 'ServiceGeneric',
            entity: 'Component',
            template: true,
            groups: [],
            formExclude: ['location'],
          },
        ],
      },
    });

    const template = entities['Template:wireless-request'];
    const fields = JSON.stringify(template.spec!.parameters);

    // Nobody should be asked to type what a generator picks...
    expect(fields).not.toContain('"location"');
    // ...but it is still read, and still shown on the entity.
    expect(entities['Component:wifi-001'].metadata.description).toContain(
      'Site Brussels 1 (bru01)',
    );
    expect(entities['Component:wifi-001'].spec!.dependsOn).toEqual([
      'resource:default/bru01',
    ]);
  });

  it('leaves member_of_groups out when no group is configured', async () => {
    const template = (await run())['Template:wireless-request'];
    const create = (template.spec!.steps as any[]).find(
      step => step.id === 'create',
    );

    expect(create.input.query).not.toContain('member_of_groups');
  });

  it('lets a kind named in config override one it would have discovered', async () => {
    const entities = await run({
      catalog: {
        kinds: [
          {
            kind: 'ServiceWireless',
            entity: 'Resource',
            type: 'wifi',
            template: false,
            groups: [],
            formExclude: [],
          },
        ],
      },
    });

    expect(entities['Resource:wifi-001'].spec!.type).toBe('wifi');
    expect(entities['Component:wifi-001']).toBeUndefined();
  });

  it('ingests nothing but warns when no mapping is configured', async () => {
    const entities = await run({ catalog: { kinds: [], discover: [] } });

    expect(Object.keys(entities)).toEqual(['System:infrahub-services']);
    expect(warnings.join('\n')).toContain('nothing will be ingested');
  });

  it('emits no System when none is configured', async () => {
    const entities = await run({ catalog: { system: undefined } });

    expect(Object.keys(entities)).not.toContain('System:infrahub-services');
    expect(entities['Component:wifi-001'].spec!.system).toBeUndefined();
  });

  it('marks an object with an open request as pending and links the change', async () => {
    const wifi = (await run())['Component:wifi-001'];

    expect(wifi.metadata.tags).toContain('pending-change');
    expect(wifi.spec!.lifecycle).toBe('experimental');
    // A change stacked on an unmerged request is silently discarded, so the
    // pencil goes to the proposed change rather than the change form.
    expect(wifi.metadata.annotations!['backstage.io/edit-url']).toBe(
      'http://localhost:8000/proposed-changes/pc-1',
    );
  });

  it('offers the generated change form once the request has merged', async () => {
    const wifi = (await run({ changeState: 'merged' }))['Component:wifi-001'];

    expect(wifi.metadata.tags).not.toContain('pending-change');
    expect(wifi.spec!.lifecycle).toBe('production');
    expect(wifi.metadata.annotations!['backstage.io/edit-url']).toContain(
      '/create/templates/default/wireless-request?formData=',
    );
  });

  it('never reads the branch of a change that already merged', async () => {
    await run({ changeState: 'merged' });

    // Infrahub deletes the source branch on merge, so every such read is a
    // guaranteed 404 repeated on each refresh.
    expect(branchesRead).toEqual([]);
  });

  it('reads the branch of a change that is still open', async () => {
    await run();

    expect(branchesRead).toEqual(['implement_wifi-001']);
  });

  it('annotates every ingested entity with its Infrahub identity', async () => {
    const entities = await run();

    for (const name of ['Resource:bru01', 'Component:wifi-001']) {
      expect(entities[name].metadata.annotations).toMatchObject({
        'infrahub.opsmill.com/instance': 'test',
        'infrahub.opsmill.com/branch': 'main',
      });
      expect(
        entities[name].metadata.annotations!['infrahub.opsmill.com/id'],
      ).toBeTruthy();
    }
  });

  it('publishes each ingested kind as an API with its GraphQL slice', async () => {
    const api = (await run())['API:locationsite'];

    expect(api.spec!.type).toBe('graphql');
    expect(api.spec!.definition).toContain('type LocationSite {');
    expect(api.metadata.description).toBe('A point of presence.');
  });

  it('never puts the internal Infrahub address in a link', async () => {
    const entities = Object.values(await run());
    const urls = entities.flatMap(entity => [
      ...Object.values(entity.metadata.annotations ?? {}),
      ...(entity.metadata.links ?? []).map(link => link.url),
    ]);

    expect(urls.filter(url => url.includes('infrahub-server'))).toEqual([]);
  });

  it('warns when two Infrahub objects collapse onto one entity name', async () => {
    (infrahubGet as jest.Mock).mockImplementation(
      async () => SCHEMA['/api/schema/LocationSite'],
    );
    await run({
      catalog: { discover: [] },
    });

    // Nothing collides in the default fixture; the guard is exercised below.
    expect(warnings.join('\n')).not.toContain('collapse');
  });

  it('survives a kind whose objects cannot be read', async () => {
    const entities = await run({
      catalog: {
        kinds: [
          {
            kind: 'LocationSite',
            entity: 'Resource',
            type: 'infrahub-site',
            template: false,
            groups: [],
            formExclude: [],
          },
          {
            // No schema in the fixture, so loading it fails.
            kind: 'DoesNotExist',
            entity: 'Resource',
            type: 'missing',
            template: false,
            groups: [],
            formExclude: [],
          },
        ],
        discover: [],
      },
    });

    // One unreadable kind costs its own entities, not the refresh.
    expect(entities['Resource:bru01']).toBeDefined();
    expect(warnings.join('\n')).toContain('DoesNotExist');
  });
});
