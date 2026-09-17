import { RootConfigService } from '@backstage/backend-plugin-api';

/**
 * A hung Infrahub must not hang a scaffolder task or a catalog refresh for
 * ever. Generous, because a generator run is deliberately slow -- but finite.
 */
const REQUEST_TIMEOUT_MS = 60_000;

export type InfrahubConfig = {
  /** Names this instance in entity annotations. */
  instance: string;
  /** Where the backend calls the API. Inside compose that is a service name. */
  address: string;
  /** Where a browser reaches the same instance, for links. */
  externalAddress: string;
  token: string;
};

export function readInfrahubConfig(config: RootConfigService): InfrahubConfig {
  const address = config.getString('infrahub.address').replace(/\/$/, '');

  return {
    instance: config.getOptionalString('infrahub.instance') ?? 'local',
    address,
    externalAddress: (
      config.getOptionalString('infrahub.externalAddress') ?? address
    ).replace(/\/$/, ''),
    token: config.getString('infrahub.token'),
  };
}

/**
 * Wraps a request so it fails with a useful message instead of hanging. Named
 * so the message says which call gave up.
 */
async function withTimeout(
  what: string,
  request: (signal: AbortSignal) => Promise<Response>,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await request(controller.signal);
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new Error(
        `Infrahub did not answer ${what} within ${REQUEST_TIMEOUT_MS / 1000}s`,
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/** POST a GraphQL query or mutation to Infrahub, on the given branch. */
export async function infrahubQuery(options: {
  config: InfrahubConfig;
  query: string;
  variables?: Record<string, unknown>;
  branch?: string;
}): Promise<Record<string, any>> {
  const { config, query, variables, branch = 'main' } = options;

  const response = await withTimeout(`POST /graphql/${branch}`, signal =>
    fetch(`${config.address}/graphql/${branch}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-INFRAHUB-KEY': config.token,
      },
      body: JSON.stringify({ query, variables: variables ?? {} }),
      signal,
    }),
  );

  const body = await response.json();
  if (!response.ok || body.errors) {
    throw new Error(
      `Infrahub GraphQL request failed (${response.status}): ${JSON.stringify(
        body.errors ?? body,
      )}`,
    );
  }

  return body.data;
}

/** GET a REST path on Infrahub. The schema lives there, not in GraphQL. */
export async function infrahubGet(
  config: InfrahubConfig,
  path: string,
): Promise<any> {
  const response = await withTimeout(`GET ${path}`, signal =>
    fetch(`${config.address}${path}`, {
      headers: { 'X-INFRAHUB-KEY': config.token },
      signal,
    }),
  );

  if (!response.ok) {
    throw new Error(
      `Infrahub GET ${path} failed (${response.status} ${response.statusText})`,
    );
  }

  return response.json();
}

/**
 * Runs work in parallel with a ceiling. Every poll fans out one request per
 * pending service and per ingested kind; serial is needlessly slow, and
 * unbounded would let a large estate hammer Infrahub on a schedule.
 */
export async function mapLimit<T, R>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;

  const runners = Array.from(
    { length: Math.max(1, Math.min(limit, items.length)) },
    async () => {
      for (;;) {
        const index = next++;
        if (index >= items.length) {
          return;
        }
        results[index] = await worker(items[index]);
      }
    },
  );

  await Promise.all(runners);
  return results;
}
