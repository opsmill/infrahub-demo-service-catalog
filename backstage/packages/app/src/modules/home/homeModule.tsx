import { createFrontendModule } from '@backstage/frontend-plugin-api';
import { HomePageWidgetBlueprint } from '@backstage/plugin-home-react/alpha';
import { MarkdownContent } from '@backstage/core-components';

const content = `
## Otter-net service portal 🦦

Every service Otter-net sells, and the network it runs on, read straight from
Infrahub. Nothing here is a copy: the catalog is Infrahub's data, and a request
you submit becomes a proposed change a network architect reviews.

### Request a service

- **[Request or change a service](/create)** — one form per service kind
  Infrahub knows about. The form is generated from that kind's Infrahub schema,
  so it always asks for exactly what the service needs.
- Submitting opens a branch, runs the generators that allocate the VLAN,
  prefix, addresses and ports, then opens a **proposed change**. Nothing is
  live until an architect merges it.
- A service waiting on review is tagged \`pending-change\`, and its pencil takes
  you to the proposed change rather than a form.

### Look around the network

- **[Service catalog](/catalog)** — every service, with the site, VLAN, prefix
  and gateway it was given, and a **Trace** tab showing everything allocated
  to it.
- **[Racks](/racks)** — rack elevations for every site, front and rear.
- **[Sites](/catalog?filters%5Bkind%5D=resource)** — points of presence, the
  devices in them, and how full their address pools are.

### Which branch am I looking at?

The branch picker in the sidebar decides which Infrahub branch the panels
query. It starts on \`main\` — production — so switch it to a request's branch to
see what that change would do before it merges.
`;

const gettingStartedWidget = HomePageWidgetBlueprint.make({
  name: 'getting-started',
  params: {
    name: 'GettingStarted',
    title: 'Welcome',
    description: 'What this portal is and where to start',
    components: async () => ({
      Content: () => <MarkdownContent content={content} />,
    }),
  },
});

export const homeModule = createFrontendModule({
  pluginId: 'home',
  extensions: [gettingStartedWidget],
});
