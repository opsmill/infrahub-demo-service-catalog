/**
 * Visual panels and pages over Infrahub, for a Backstage frontend.
 *
 * The panels find their Infrahub node through the annotations the entity
 * provider writes, and query Infrahub through the Backstage `proxy` plugin, so
 * nothing has to be synchronised into the catalog for them to work.
 *
 * @packageDocumentation
 */

export {
  infrahubPlugin as default,
  infrahubPlugin,
  infrahubModule,
} from './plugin';

/** For building panels of your own on the same plumbing. */
export { useInfrahubQuery, useInfrahubNode } from './client';
export type { QueryState } from './client';
export { useInfrahubBranch, setInfrahubBranch } from './branch';
export { BranchPicker } from './BranchPicker';
export { InfrahubGraph, roleFor } from './panels/graph';
export type { GraphNode, GraphEdge, KindRole } from './panels/graph';
export { useKindColours, useStatusColours } from './colours';
