/**
 * Mirroring Infrahub into the Backstage catalog, and driving it from the
 * scaffolder.
 *
 * Two backend modules, added independently because a consumer may want only
 * one of them:
 *
 * ```ts
 * import {
 *   infrahubCatalogModule,
 *   infrahubActionsModule,
 * } from '@opsmill/backstage-plugin-infrahub-backend';
 *
 * backend.add(infrahubCatalogModule);
 * backend.add(infrahubActionsModule);
 * ```
 *
 * @packageDocumentation
 */

export { infrahubCatalogModule, InfrahubEntityProvider } from './provider';
export { infrahubActionsModule } from './actions';
