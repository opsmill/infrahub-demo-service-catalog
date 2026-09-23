/**
 * Talking to Infrahub from a Backstage backend: the HTTP client, and waiting
 * for the generators that expand a node after a mutation returns.
 *
 * Nothing here knows anything about a particular Infrahub schema, so any
 * backend module can build on it -- an entity provider, a scaffolder action, or
 * something this repo has not thought of.
 *
 * @packageDocumentation
 */

export {
  infrahubQuery,
  infrahubGet,
  readInfrahubConfig,
  mapLimit,
} from './client';
export type { InfrahubConfig } from './client';

export { awaitGenerators } from './generators';
export type { AwaitOptions, AwaitResult } from './generators';
