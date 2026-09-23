import { RootConfigService } from '@backstage/backend-plugin-api';

/** What one Infrahub kind becomes in the catalog. */
export type KindMapping = {
  kind: string;
  entity: 'Component' | 'Resource' | 'System' | 'API';
  /** The entity's `spec.type`, and the tag every such entity carries. */
  type: string;
  /** Whether to generate a create/change scaffolder template for the kind. */
  template: boolean;
  /**
   * Groups a generated create puts the new object into. An Infrahub generator
   * definition targets a *group*, so an object created outside it is never
   * expanded -- and there is nothing in the schema linking a kind to the group
   * its generators watch, which is why this has to be said here.
   */
  groups: string[];
  /**
   * Fields the generated form must not offer, on top of `status`. A field a
   * generator allocates -- a VLAN, a prefix, a gateway -- is still read and
   * still shown on the entity; asking a person to type it is what makes a
   * generated form look wrong.
   */
  formExclude: string[];
  /** The generic it was discovered under, when it was not named directly. */
  discoveredUnder?: string;
};

export type CatalogConfig = {
  refreshMinutes: number;
  owner: string;
  system?: string;
  /** Kinds named directly in config. */
  kinds: KindMapping[];
  /** Generics whose descendants are ingested, resolved against the schema. */
  discover: {
    generic: string;
    entity: KindMapping['entity'];
    template: boolean;
    groups: string[];
    formExclude: string[];
  }[];
};

/**
 * `LocationSite` becomes `location-site`, which reads better as a `spec.type`
 * and as a tag than the kind does. A leading `Service` is dropped, because
 * `dedicated-internet` says what a service is and `service-dedicated-internet`
 * only repeats the namespace.
 *
 * Used for both named and discovered kinds so the two agree: naming a kind in
 * config to change one thing about it must not silently change its type too.
 */
export function slugFor(kind: string): string {
  return kind
    .replace(/^Service/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1-$2')
    .toLowerCase();
}

/**
 * Reads `infrahub.catalog`. Every field has a default, so a consumer who
 * declares nothing but `discover` still gets a working catalog.
 */
export function readCatalogConfig(config: RootConfigService): CatalogConfig {
  const root = config.getOptionalConfig('infrahub.catalog');

  const kinds = (root?.getOptionalConfigArray('kinds') ?? []).map(entry => {
    const kind = entry.getString('kind');
    const entity =
      (entry.getOptionalString('entity') as KindMapping['entity']) ??
      'Resource';

    return {
      kind,
      entity,
      type: entry.getOptionalString('type') ?? slugFor(kind),
      // A site is reference data; a service is something someone requests.
      template: entry.getOptionalBoolean('template') ?? entity === 'Component',
      groups: entry.getOptionalStringArray('groups') ?? [],
      formExclude: entry.getOptionalStringArray('formExclude') ?? [],
    };
  });

  const discover = (root?.getOptionalConfigArray('discover') ?? []).map(
    entry => ({
      generic: entry.getString('generic'),
      entity:
        (entry.getOptionalString('entity') as KindMapping['entity']) ??
        'Component',
      template: entry.getOptionalBoolean('template') ?? true,
      groups: entry.getOptionalStringArray('groups') ?? [],
      formExclude: entry.getOptionalStringArray('formExclude') ?? [],
    }),
  );

  return {
    refreshMinutes: root?.getOptionalNumber('refreshMinutes') ?? 1,
    owner: root?.getOptionalString('owner') ?? 'user:default/guest',
    // No default: a plugin should not invent a System entity nobody asked
    // for. Name one and every ingested Component is grouped under it.
    system: root?.getOptionalString('system'),
    kinds,
    discover,
  };
}
