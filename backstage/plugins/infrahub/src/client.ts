import { useEffect, useState } from 'react';
import {
  useApi,
  discoveryApiRef,
  fetchApiRef,
} from '@backstage/core-plugin-api';
import { useEntity } from '@backstage/plugin-catalog-react';
import { INFRAHUB_ANNOTATIONS } from '@opsmill/backstage-plugin-infrahub-common';
import { useInfrahubBranch } from './branch';

const INFRAHUB_ID = INFRAHUB_ANNOTATIONS.id;
const INFRAHUB_KIND = INFRAHUB_ANNOTATIONS.kind;

/** A panel should fail visibly rather than spin for ever. */
const TIMEOUT_MS = 30_000;

export type QueryState<T> = { data?: T; loading: boolean; error?: Error };

/**
 * Runs a GraphQL query against Infrahub through the Backstage proxy, on the
 * branch currently selected in the sidebar. The proxy injects the API token, so
 * none of this needs credentials in the browser.
 */
export async function infrahubFetch<T>(options: {
  url: string;
  query: string;
  variables: Record<string, unknown>;
  branch: string;
  fetchFn: typeof fetch;
  signal?: AbortSignal;
}): Promise<T> {
  const response = await options.fetchFn(options.url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: options.query,
      variables: options.variables,
    }),
    signal: options.signal,
  });

  const body = await response.json().catch(() => undefined);

  if (!response.ok) {
    const detail = body?.errors?.[0]?.message;
    throw new Error(
      `Infrahub returned ${response.status} on branch ${options.branch}${
        detail ? `: ${detail}` : ''
      }`,
    );
  }
  if (body?.errors?.length) {
    // Name the branch: the same query can be valid on main and not on a branch
    // whose schema differs.
    throw new Error(`${body.errors[0].message} (branch ${options.branch})`);
  }
  if (!body?.data) {
    throw new Error(`Infrahub returned no data on branch ${options.branch}`);
  }

  return body.data as T;
}

export function useInfrahubQuery<T>(
  query: string,
  variables: Record<string, unknown>,
  deps: unknown[] = [],
  /** Skip the request entirely, for a query that depends on a later choice. */
  skip = false,
  /**
   * Pin the query to one branch instead of following the selection. The branch
   * list needs this: asking a deleted branch for the list of branches fails,
   * and then nothing can recover the selection.
   */
  onBranch?: string,
): QueryState<T> {
  const discovery = useApi(discoveryApiRef);
  const { fetch: fetchApi } = useApi(fetchApiRef);
  const { branch: selected } = useInfrahubBranch();
  const branch = onBranch ?? selected;
  const [state, setState] = useState<QueryState<T>>({ loading: true });

  useEffect(() => {
    if (skip) {
      setState({ loading: false });
      return undefined;
    }

    let live = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    setState({ loading: true });

    (async () => {
      const base = await discovery.getBaseUrl('proxy');
      const data = await infrahubFetch<T>({
        url: `${base}/infrahub/graphql/${branch}`,
        query,
        variables,
        branch,
        fetchFn: fetchApi,
        signal: controller.signal,
      });
      if (live) {
        setState({ data, loading: false });
      }
    })().catch(error => {
      if (!live) {
        return;
      }
      const reason =
        (error as Error).name === 'AbortError'
          ? new Error(
              `Infrahub did not answer within ${
                TIMEOUT_MS / 1000
              }s on branch ${branch}`,
            )
          : (error as Error);
      setState({ loading: false, error: reason });
    });

    return () => {
      live = false;
      clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, skip, branch]);

  return state;
}

/** The Infrahub node behind the entity being viewed. */
export function useInfrahubNode() {
  const { entity } = useEntity();
  const viewUrl = entity.metadata.annotations?.['backstage.io/view-url'] ?? '';

  return {
    id: entity.metadata.annotations?.[INFRAHUB_ID],
    kind: entity.metadata.annotations?.[INFRAHUB_KIND],
    title: entity.metadata.title ?? entity.metadata.name,
    /**
     * The browser-facing Infrahub base URL, taken from the entity's own view
     * link rather than configured twice.
     */
    infrahubUrl: viewUrl.split('/objects/')[0],
  };
}
