import { ConfigReader } from '@backstage/config';
import { RootConfigService } from '@backstage/backend-plugin-api';
import { readCatalogConfig, slugFor } from './config';

const read = (catalog: Record<string, unknown>) =>
  readCatalogConfig(
    new ConfigReader({ infrahub: { catalog } as never }) as RootConfigService,
  );

describe('slugFor', () => {
  it('turns an Infrahub kind into a readable type', () => {
    expect(slugFor('LocationSite')).toBe('location-site');
  });

  it('drops a leading Service, which only repeats the namespace', () => {
    // And it must match what discovery produces, or naming a kind in config to
    // change one thing about it would silently change its type too.
    expect(slugFor('ServiceDedicatedInternet')).toBe('dedicated-internet');
  });

  it('keeps runs of capitals together', () => {
    expect(slugFor('IpamIPAddress')).toBe('ipam-ip-address');
  });
});

describe('readCatalogConfig', () => {
  it('works with nothing configured at all', () => {
    const config = readCatalogConfig(new ConfigReader({}) as RootConfigService);

    expect(config).toEqual({
      refreshMinutes: 1,
      owner: 'user:default/guest',
      system: undefined,
      kinds: [],
      discover: [],
    });
  });

  it('defaults a named kind to a Resource with a slug for its type', () => {
    expect(read({ kinds: [{ kind: 'LocationSite' }] }).kinds).toEqual([
      {
        kind: 'LocationSite',
        entity: 'Resource',
        type: 'location-site',
        template: false,
        groups: [],
        formExclude: [],
      },
    ]);
  });

  it('gives a Component a template but a Resource none', () => {
    const { kinds } = read({
      kinds: [
        { kind: 'ServiceVoice', entity: 'Component' },
        { kind: 'LocationSite' },
      ],
    });

    // A service is something a portal user requests; a site is reference data.
    expect(kinds.map(kind => kind.template)).toEqual([true, false]);
  });

  it('honours an explicit type and template', () => {
    expect(
      read({
        kinds: [
          {
            kind: 'LocationSite',
            entity: 'Resource',
            type: 'infrahub-site',
            template: true,
          },
        ],
      }).kinds[0],
    ).toEqual({
      kind: 'LocationSite',
      entity: 'Resource',
      type: 'infrahub-site',
      template: true,
      groups: [],
      formExclude: [],
    });
  });

  it('defaults a discover rule to templated Components', () => {
    expect(
      read({ discover: [{ generic: 'ServiceGeneric' }] }).discover,
    ).toEqual([
      {
        generic: 'ServiceGeneric',
        entity: 'Component',
        template: true,
        groups: [],
        formExclude: [],
      },
    ]);
  });

  it('carries the groups a generated create should join', () => {
    expect(
      read({ kinds: [{ kind: 'ServiceVoice', groups: ['automated_voice'] }] })
        .kinds[0].groups,
    ).toEqual(['automated_voice']);
  });

  it('emits no System unless one is named', () => {
    expect(read({}).system).toBeUndefined();
    expect(read({ system: 'my-services' }).system).toBe('my-services');
  });
});
