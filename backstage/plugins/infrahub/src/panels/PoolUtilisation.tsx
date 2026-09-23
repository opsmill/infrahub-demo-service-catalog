import {
  InfoCard,
  Progress,
  ResponseErrorPanel,
} from '@backstage/core-components';
import { useInfrahubQuery } from '../client';
import { useKindColours, useStatusColours } from '../colours';

/**
 * Every resource pool, with how full it is. Infrahub computes utilisation, so
 * this reports it rather than deriving it from allocations.
 */
const QUERY = `
  {
    CoreResourcePool {
      edges { node { id display_label __typename } }
    }
  }
`;

const UTILISATION = `
  query ($pool: String!) {
    InfrahubResourcePoolUtilization(pool_id: $pool) {
      count
      utilization
      utilization_default_branch
    }
  }
`;

type Pools = {
  CoreResourcePool: {
    edges: {
      node: { id: string; display_label: string; __typename: string };
    }[];
  };
};

/** The unallocated remainder of a pool. */
const TRACK_BACKGROUND = '#dde3e2';

const POOL_LABELS: Record<string, string> = {
  CoreIPPrefixPool: 'Prefixes',
  CoreIPAddressPool: 'Addresses',
  CoreNumberPool: 'Numbers',
};

const readout = (state: { error?: Error; loading: boolean; used: number }) => {
  if (state.error) return 'unavailable';
  if (state.loading) return '…';
  return `${state.used.toFixed(1)}%`;
};

function Bar(props: {
  pool: { id: string; display_label: string; __typename: string };
}) {
  const colours = useKindColours();
  const status = useStatusColours();
  const { data, loading, error } = useInfrahubQuery<{
    InfrahubResourcePoolUtilization: {
      count: number;
      utilization: number;
      utilization_default_branch: number;
    };
  }>(UTILISATION, { pool: props.pool.id }, [props.pool.id]);

  const used = data?.InfrahubResourcePoolUtilization.utilization ?? 0;
  const onMain =
    data?.InfrahubResourcePoolUtilization.utilization_default_branch ?? 0;
  // Anything above main is allocated on a branch: requested, not yet merged.
  const pending = Math.max(0, used - onMain);

  return (
    <div style={{ marginBottom: 18 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 13,
          marginBottom: 4,
        }}
      >
        <span style={{ fontWeight: 600 }}>
          {props.pool.display_label}{' '}
          <span style={{ opacity: 0.6, fontWeight: 400 }}>
            {POOL_LABELS[props.pool.__typename] ?? props.pool.__typename}
          </span>
        </span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>
          {readout({ error, loading, used })}
        </span>
      </div>
      <div
        style={{
          height: 12,
          borderRadius: 6,
          background: TRACK_BACKGROUND,
          overflow: 'hidden',
          display: 'flex',
        }}
      >
        <div
          style={{ width: `${onMain}%`, background: colours.device }}
          title={`${onMain.toFixed(1)}% allocated on main`}
        />
        <div
          style={{
            width: `${pending}%`,
            // Hatched, the way a pending request is drawn everywhere else.
            background: `repeating-linear-gradient(45deg,${status.pending},${status.pending} 4px,${TRACK_BACKGROUND} 4px,${TRACK_BACKGROUND} 8px)`,
          }}
          title={`${pending.toFixed(1)}% allocated on a branch, pending review`}
        />
      </div>
    </div>
  );
}

export function PoolUtilisation() {
  const { data, loading, error } = useInfrahubQuery<Pools>(QUERY, {});

  if (loading) return <Progress />;
  if (error) return <ResponseErrorPanel error={error} />;

  const pools = data!.CoreResourcePool.edges.map(edge => edge.node);

  return (
    <InfoCard
      title="Resource pools"
      subheader="Solid is allocated on main; hatched is allocated on a branch and still under review"
    >
      {pools.map(pool => (
        <Bar key={pool.id} pool={pool} />
      ))}
    </InfoCard>
  );
}
