import DnsIcon from '@material-ui/icons/Dns';
import {
  createFrontendModule,
  createFrontendPlugin,
  PageBlueprint,
} from '@backstage/frontend-plugin-api';
import {
  EntityCardBlueprint,
  EntityContentBlueprint,
} from '@backstage/plugin-catalog-react/alpha';

/**
 * Visual panels over Infrahub. Each is filtered to the entity kind whose data
 * it can actually draw, so a panel never appears on a page with nothing to show.
 */

const serviceTraceTab = EntityContentBlueprint.make({
  name: 'service-trace',
  params: {
    path: '/trace',
    title: 'Trace',
    filter: 'kind:component',
    loader: () => import('./panels/ServiceTrace').then(m => <m.ServiceTrace />),
  },
});

const siteMapTab = EntityContentBlueprint.make({
  name: 'site-map',
  params: {
    path: '/site-map',
    title: 'Site map',
    filter: { kind: 'resource', 'spec.type': 'infrahub-site' },
    loader: () => import('./panels/SiteMap').then(m => <m.SiteMap />),
  },
});

const rackElevationTab = EntityContentBlueprint.make({
  name: 'rack-elevation',
  params: {
    path: '/racks',
    title: 'Racks',
    filter: { kind: 'resource', 'spec.type': 'infrahub-site' },
    loader: () =>
      import('./panels/RackElevation').then(m => <m.RackElevation />),
  },
});

/** The same drawing on a rack's own page, showing just that rack. */
const rackCard = EntityCardBlueprint.make({
  name: 'rack-detail',
  params: {
    type: 'content',
    filter: { kind: 'resource', 'spec.type': 'infrahub-rack' },
    loader: () =>
      import('./panels/RackElevation').then(m => <m.RackElevation />),
  },
});

const devicePortsCard = EntityCardBlueprint.make({
  name: 'device-ports',
  params: {
    type: 'content',
    filter: { kind: 'resource', 'spec.type': 'infrahub-device' },
    loader: () => import('./panels/DevicePorts').then(m => <m.DevicePorts />),
  },
});

const prefixMapCard = EntityCardBlueprint.make({
  name: 'prefix-map',
  params: {
    type: 'content',
    filter: { kind: 'component' },
    loader: () => import('./panels/PrefixMap').then(m => <m.PrefixMap />),
  },
});

const poolUtilisationCard = EntityCardBlueprint.make({
  name: 'pool-utilisation',
  params: {
    // A compact summary, so it belongs beside About rather than at the bottom
    // of the page under the relations graph.
    type: 'info',
    filter: { kind: 'system' },
    loader: () =>
      import('./panels/PoolUtilisation').then(m => <m.PoolUtilisation />),
  },
});

/**
 * A standalone page, with its own nav entry and no catalog entity behind it.
 * The right shape for a view that only needs to query Infrahub.
 */
const racksPage = PageBlueprint.make({
  params: {
    path: '/racks',
    title: 'Racks',
    icon: <DnsIcon />,
    noHeader: true,
    loader: () => import('./pages/RacksPage').then(m => <m.RacksPage />),
  },
});

/**
 * Its own plugin rather than a module extension, so the page gets the default
 * page id for the plugin and therefore a sidebar entry.
 */
export const infrahubPlugin = createFrontendPlugin({
  pluginId: 'infrahub',
  extensions: [racksPage],
});

export const infrahubModule = createFrontendModule({
  pluginId: 'catalog',
  extensions: [
    serviceTraceTab,
    siteMapTab,
    rackElevationTab,
    rackCard,
    devicePortsCard,
    prefixMapCard,
    poolUtilisationCard,
  ],
});
