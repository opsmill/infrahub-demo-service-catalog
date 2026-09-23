import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TextField from '@material-ui/core/TextField';
import Autocomplete from '@material-ui/lab/Autocomplete';
import {
  Content,
  ContentHeader,
  Header,
  Page,
  Progress,
  ResponseErrorPanel,
  SupportButton,
} from '@backstage/core-components';
import { useInfrahubQuery } from '../client';
import { Rack, RACK_FIELDS, RackNode } from '../panels/RackElevation';

/**
 * Two queries on purpose. The first is only what the picker needs -- a name and
 * its site -- filtered and paged by Infrahub, so neither the page cost nor the
 * number of options grows with how many racks exist. The second fetches one
 * rack's contents, and only when one is chosen.
 */
const LIST_QUERY = `
  query ($search: String, $limit: Int) {
    LocationRack(
      partial_match: true
      shortname__value: $search
      limit: $limit
      order: { disable: false }
    ) {
      count
      edges {
        node {
          id
          shortname { value }
          display_label
          parent { node { display_label } }
        }
      }
    }
  }
`;

/**
 * By shortname, not id: the chosen rack has to load even when it is not on the
 * page of options currently in hand.
 */
const DETAIL_QUERY = `
  query ($shortname: String!) {
    LocationRack(shortname__value: $shortname) {
      edges {
        node {
          ${RACK_FIELDS}
          parent { node { display_label } }
        }
      }
    }
  }
`;

/** How many options to offer at once. A picker, not a listing. */
const PAGE = 50;

export type RackOption = {
  id: string;
  shortname: { value: string };
  display_label: string;
  parent: { node: { display_label: string } | null } | null;
};

type RackList = {
  LocationRack: { count: number; edges: { node: RackOption }[] };
};

type RackDetail = {
  LocationRack: {
    edges: {
      node: RackNode & {
        parent: { node: { display_label: string } | null } | null;
      };
    }[];
  };
};

/**
 * The options to offer, with the selected rack kept among them. A search that
 * excludes the selection must not blank the picker, and MUI rejects a value it
 * cannot find in its options.
 */
export function withSelected(
  options: RackOption[],
  selected: RackOption | null,
) {
  if (!selected || options.some(option => option.id === selected.id)) {
    return options;
  }
  return [selected, ...options];
}

/** How much of a rack is still free, which is the question people ask of one. */
export function capacity(rack: RackNode) {
  const units = rack.height.value ?? 0;
  const used = rack.mounted_devices.edges.reduce(
    (total, edge) => total + (edge.node.device_type?.node?.height.value ?? 1),
    0,
  );
  return { units, used, free: Math.max(0, units - used) };
}

export function RacksPage() {
  const [params, setParams] = useSearchParams();
  const [typed, setTyped] = useState('');
  const [search, setSearch] = useState('');

  // Debounced so a query goes out per pause, not per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(typed), 250);
    return () => clearTimeout(timer);
  }, [typed]);

  const list = useInfrahubQuery<RackList>(
    LIST_QUERY,
    { search: search || null, limit: PAGE },
    [search],
  );

  const options = useMemo(
    () => list.data?.LocationRack.edges.map(edge => edge.node) ?? [],
    [list.data],
  );

  // The URL owns the selection, so a rack elevation is a shareable link.
  const chosen = params.get('rack');

  // Nothing chosen yet: show the first rack rather than an empty page.
  useEffect(() => {
    if (!chosen && options.length > 0) {
      setParams({ rack: options[0].shortname.value }, { replace: true });
    }
  }, [chosen, options, setParams]);

  const detail = useInfrahubQuery<RackDetail>(
    DETAIL_QUERY,
    { shortname: chosen },
    [chosen],
    !chosen,
  );
  const rack = detail.data?.LocationRack.edges[0]?.node;

  const total = list.data?.LocationRack.count ?? 0;
  const site = rack?.parent?.node?.display_label;

  // From the detail query, not from the current page of options -- see
  // withSelected above.
  const selected: RackOption | null = rack
    ? {
        id: rack.id,
        shortname: rack.shortname,
        display_label: rack.display_label,
        parent: rack.parent,
      }
    : null;
  const shown = withSelected(options, selected);

  return (
    <Page themeId="tool">
      <Header
        title="Racks"
        subtitle="Rack elevations, read straight from Infrahub"
      />
      <Content>
        <ContentHeader
          title={
            rack
              ? [site, rack.display_label].filter(Boolean).join(' — ')
              : 'Racks'
          }
        >
          <SupportButton>
            Typing filters the racks in Infrahub rather than in the browser, and
            only {PAGE} are offered at a time, so the page costs the same
            whether there are four racks or four thousand. The elevation is
            fetched for the selected rack only.
          </SupportButton>
        </ContentHeader>

        {list.error && <ResponseErrorPanel error={list.error} />}

        <Autocomplete
          options={shown}
          loading={list.loading}
          style={{ minWidth: 380 }}
          // Infrahub already filtered; filtering again would hide matches that
          // the shortname matched but the label does not show.
          filterOptions={x => x}
          // Focusing highlights the current rack's name, so typing replaces it
          // rather than appending to it and matching nothing.
          selectOnFocus
          getOptionLabel={option => option.display_label}
          getOptionSelected={(option, chosenOption) =>
            option.id === chosenOption.id
          }
          groupBy={option => option.parent?.node?.display_label ?? 'Unassigned'}
          value={selected}
          onChange={(_event, option) => {
            if (option) {
              setParams({ rack: option.shortname.value });
            } else {
              // The X. Keep showing the rack -- an empty page is worse -- but
              // put every rack back in the picker.
              setTyped('');
            }
          }}
          onInputChange={(_event, input, reason) => {
            // Only typing is a search; 'reset' is a selection rewriting the
            // input, which must not become one.
            if (reason === 'input') {
              setTyped(input);
            }
          }}
          renderInput={inputParams => (
            <TextField
              {...inputParams}
              label={`Rack${total ? ` (${total} matching)` : ''}`}
              variant="outlined"
              size="small"
              placeholder="Type to search"
            />
          )}
        />

        <div style={{ marginTop: 20 }}>
          {detail.loading && <Progress />}
          {detail.error && <ResponseErrorPanel error={detail.error} />}
          {rack && (
            <>
              <div style={{ fontSize: 13, opacity: 0.75, marginBottom: 12 }}>
                {(() => {
                  const { units, used, free } = capacity(rack);
                  return `${used}U used of ${units}U · ${free}U free · ${rack.mounted_devices.edges.length} devices · hatched is rear-facing`;
                })()}
              </div>
              <Rack rack={rack} />
            </>
          )}
        </div>

        {!list.loading && options.length === 0 && (
          <div style={{ fontSize: 13, opacity: 0.7, marginTop: 20 }}>
            {search
              ? `No rack matches "${search}".`
              : 'No racks in Infrahub yet.'}
          </div>
        )}
      </Content>
    </Page>
  );
}
