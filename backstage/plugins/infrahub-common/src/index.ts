/**
 * Names shared by the Infrahub frontend and backend plugins.
 *
 * @packageDocumentation
 */

/**
 * Annotations the entity provider writes onto every entity it ingests, and the
 * frontend reads back to find the Infrahub object an entity came from.
 *
 * They live here rather than in either plugin because both sides need them, and
 * a string that has to match across a process boundary is exactly the thing
 * that drifts when it is written out twice.
 */
export const INFRAHUB_ANNOTATIONS = {
  /** Which Infrahub the entity came from, so two instances do not look alike. */
  instance: 'infrahub.opsmill.com/instance',
  /** The Infrahub node id, which every panel needs to query anything. */
  id: 'infrahub.opsmill.com/id',
  /** The node's Infrahub kind, e.g. `ServiceDedicatedInternet`. */
  kind: 'infrahub.opsmill.com/kind',
  /** The branch the entity was read from. */
  branch: 'infrahub.opsmill.com/branch',
} as const;

/** The default Infrahub branch, and the one the catalog is ingested from. */
export const DEFAULT_BRANCH = 'main';
