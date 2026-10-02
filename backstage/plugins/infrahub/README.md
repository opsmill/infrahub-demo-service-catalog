# @opsmill/backstage-plugin-infrahub

Visual panels and pages over [Infrahub](https://opsmill.com) for Backstage.

Panels find their Infrahub node through the annotations the entity provider
writes, and query Infrahub through the Backstage `proxy` plugin, so nothing has
to be synchronised into the catalog for them to work.

## What you get

| Extension      | Where it appears           | Draws                                                            |
| -------------- | -------------------------- | ---------------------------------------------------------------- |
| Trace          | tab on a Component         | Everything allocated to a service, from `InfrahubReachableNodes` |
| Site map       | tab on a site Resource     | The site's services and devices                                  |
| Racks          | tab on a site Resource     | Every rack at the site, as an elevation                          |
| Elevation      | card on a rack Resource    | That one rack, front and rear                                    |
| Ports          | card on a device Resource  | Every interface, coloured by status                              |
| Resource pools | info card on a System      | Pool utilisation, split by main and branch                       |
| IP allocation  | card on a Component        | A prefix cell by cell, marking the gateway                       |
| `/racks`       | its own page and nav entry | A searchable rack picker                                         |

## Install

```ts
// packages/app/src/App.tsx
import {
  infrahubModule,
  infrahubPlugin,
} from '@opsmill/backstage-plugin-infrahub';

export default createApp({
  features: [catalogPlugin, infrahubModule, infrahubPlugin],
});
```

Add the branch picker wherever your sidebar is defined:

```tsx
import { BranchPicker } from '@opsmill/backstage-plugin-infrahub';
```

The panels reach Infrahub through a proxy endpoint, which injects the token so
it never reaches the browser:

```yaml
proxy:
  endpoints:
    '/infrahub':
      target: http://infrahub-server:8000
      headers:
        X-INFRAHUB-KEY: ${INFRAHUB_API_TOKEN}
```

## Colours follow your theme

The plugin decides which _role_ a colour plays; your theme decides what the
role looks like. `useKindColours` maps onto `palette.primary`, `info`,
`success`, `warning` and `secondary`, and `useStatusColours` uses Backstage's
`palette.status`. Fill those in and the panels come out in your brand. Install
no theme and you get MUI's defaults, which are distinct enough to read.

## Building your own panels

```ts
import {
  useInfrahubQuery,
  useInfrahubNode,
  InfrahubGraph,
} from '@opsmill/backstage-plugin-infrahub';
```

`useInfrahubNode()` gives you the entity's Infrahub id, kind and browser-facing
URL. `useInfrahubQuery()` runs a GraphQL query on the branch currently selected
in the sidebar, with a timeout and cancellation already handled.

## Pointing the panels at your own entities

Each panel is filtered to the entity kind whose data it can draw, using the
`spec.type` values the entity provider emits by default. If your
`infrahub.catalog` config uses different types, retarget the panels from config
-- every extension's `filter` is configurable, so this needs no fork:

```yaml
app:
  extensions:
    - entity-content:catalog/site-map:
        config:
          filter: { kind: resource, 'spec.type': my-site }
    - entity-card:catalog/device-ports:
        config:
          filter: { kind: resource, 'spec.type': my-device }
```

The extension ids follow `<kind>:<pluginId>/<name>`: `site-map`,
`rack-elevation` and `service-trace` are `entity-content:catalog/...`;
`rack-detail`, `device-ports`, `prefix-map` and `pool-utilisation` are
`entity-card:catalog/...`. Set `filter` to `false`-y config or disable the
extension outright (`- entity-card:catalog/prefix-map: false`) to drop a panel
you do not want.

## Caveat

`RackElevation`, `DevicePorts` and `PrefixMap` read DCIM and IPAM _field_ names
(`position`, `rack_face`, `interfaces`, `prefix`). That is a common Infrahub
schema pattern but not a universal one, so a materially different schema needs
those field names parameterised -- config can retarget which entities a panel
appears on, but not yet what it reads.
