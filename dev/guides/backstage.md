# Backstage Portal

An alternative service portal to the Streamlit app, under `backstage/`. Same
Infrahub flow: a request lands on its own branch and opens a proposed change.

## Running it

As part of the stack, which is how a demo should run it:

```bash
invoke backstage-install   # once, installs Node dependencies
invoke backstage-build     # bundle on the host, then the image
invoke start               # brings the backstage service up with the rest
```

Or as a dev server, for working on it, with hot reload:

```bash
invoke backstage           # Ctrl-C to stop
invoke backstage-test      # unit tests
```

Either way it is <http://localhost:3001>; sign in as Guest. Run one at a time,
they want the same port. 3001 because Semaphore already holds 3000.

The dev server puts the frontend on 3001 and the backend on 7007, and reads
`INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` from the environment. In the
container the backend serves the frontend bundle, so 3001 is both, and compose
passes the Infrahub service name instead.

The image copies a bundle built on the host, so `invoke backstage-build` has to
run before compose builds the image — `invoke start --build` alone will use a
stale bundle. `app-config.docker.yaml` layers the container's differences over
`app-config.yaml`: the URLs, an in-memory database, guest sign-in enabled
outside development, and a catalog that drops the scaffolded sample entities.

Backstage is a separate Node/TypeScript workspace with its own `yarn`, prettier
and eslint, so `.yamllint.yml` ignores `/backstage`, and `backstage/.gitignore`
governs what is committed there. Nothing in it is Python.

## How this is packaged

The Infrahub integration lives in plugins rather than in the app, so it can be
installed rather than copied:

| Package | Role | Holds |
| --- | --- | --- |
| `plugins/infrahub-common` | isomorphic | The annotation names and the default branch -- both sides need them, and a string that has to match across a process boundary is what drifts when it is written twice |
| `plugins/infrahub-node` | node library | `infrahubQuery`, `infrahubGet`, `readInfrahubConfig`, `mapLimit`, `awaitGenerators`. Knows nothing about any particular schema, so any backend module can build on it |
| `plugins/infrahub` | frontend plugin | The panels, pages, branch picker, `useInfrahubQuery` and the React Flow wrapper |
| `plugins/infrahub-backend` | backend modules | `infrahubCatalogModule` (the entity provider) and `infrahubActionsModule` (the three scaffolder actions) |

`packages/app` and `packages/backend` hold only what is genuinely this demo's:
the Otter-net theme and branding, the sidebar, the home page, and the two lines
that add the modules.

All four plugins build to a publishable `dist` with type declarations, are
Apache-2.0, are scoped `@opsmill/backstage-plugin-infrahub-*`, and carry a
README written for someone installing them. The app consumes them as workspace
dependencies, which is exactly how an outside consumer would, so the extraction
cannot silently rot.

The two backend modules are added separately rather than as one default export,
because a consumer may want the scaffolder actions without the provider, or the
other way round:

```ts
backend.add(infrahubCatalogModule);
backend.add(infrahubActionsModule);
```

`infrahub:catalog:refresh` is the one coupling between them -- it asks the
provider to read now -- so it needs the catalog module installed.

### The provider takes its mapping from config

There is no per-kind code in the provider. Which Infrahub kinds become which
entities comes from `infrahub.catalog`; what each entity *says* comes from that
kind's own Infrahub schema. This demo's mapping lives in `app-config.yaml`:

```yaml
infrahub:
  catalog:
    system: infrahub-services
    kinds:
      - { kind: LocationSite, entity: Resource, type: infrahub-site }
      - { kind: LocationRack, entity: Resource, type: infrahub-rack }
      - { kind: DcimGenericDevice, entity: Resource, type: infrahub-device }
    discover:
      - { generic: ServiceGeneric, entity: Component }
```

Three parts of the Infrahub schema carry the weight:

- **`human_friendly_id` names the entity.** Every kind's schema declares it --
  `shortname__value` for a site, `service_identifier__value` for a service.
- **The schema declares the identifier attribute too**, which is how the
  generated template knows which field to look an object up by.
- **Relationship display labels go in the description**, which is where the
  VLAN, prefix and gateway detail on a service comes from.

Two things the generic query has to respect, both pinned by tests: ask each
kind only for the fields its own schema declares, because a kind that lacks a
field fails the *entire* GraphQL query; and key the pencil on a proposed change
being *open*, not on one existing, or a merged change keeps sending the pencil
at the change rather than the change form.

The panels filter on the `spec.type` values the provider emits, so a consumer
who configures different types needs the panels retargeted to match. That needs
no code: every entity extension's `filter` is configurable from
`app-config.yaml`.

### How the frontend plugin stays reusable

A plugin cannot import the app's theme, which is what forces the layering: the
plugin decides which *role* a colour plays and the app's theme decides what that
role looks like. `useKindColours` maps roles onto `palette.primary`, `info`,
`success`, `warning` and `secondary`; `useStatusColours` uses Backstage's own
`palette.status`, which exists for exactly this. So the Otter-net theme fills
those slots and a rack elevation comes out on-brand without the plugin knowing
Otter-net exists -- and an app that installs no theme still gets MUI's defaults,
which are distinct enough to read.

The same split shows up twice more, and it is worth copying: `roleFor(kind)`
classifies an Infrahub kind by namespace and `cellRole(state)` says what an
address cell *means*. Both are pure and tested; neither knows a colour. The
components do the mapping.

`react-router-dom` is a **peer** dependency, not a regular one. Resolved as a
regular dependency it lands on v7 while Backstage is on v6, which is a second
router instance rather than a lint gripe.

## Visual panels and pages

Everything visual lives in the frontend plugin,
`backstage/plugins/infrahub/src/`; `packages/app/src/App.tsx` installs it.

Panels attached to catalog entities:

| Panel | Where | Draws |
| --- | --- | --- |
| Trace | tab on a service | Its allocated objects, from `InfrahubReachableNodes` |
| Site map | tab on a site | Its services and devices |
| Racks | tab on a site | Every rack at the site, as an elevation |
| Elevation | card on a rack | That one rack |
| Ports | card on a device | Every interface, coloured by status, with the service holding it |
| Resource pools | info card on the System | Pool utilisation, split by main and branch |
| IP allocation | card on a service | Its prefix cell by cell, marking the gateway |

And one standalone page, `/racks`, with its own sidebar entry. A page is the
right shape when a view only needs to query Infrahub: nothing has to be
synchronised into the catalog for it to work, which matters for reference data
like racks that nobody owns or searches for. It also shows the pattern to copy:
a light query for the picker, then a second query for the selection only, so the
page cost scales with neither the number of racks nor their contents.

The picker is worth reading before writing another. Typing filters in Infrahub
(`partial_match: true`, `limit: 50`), not in the browser, so the option list
stays the same size whatever the rack count is. Three things follow from that:

- The chosen rack is loaded **by shortname**, and the selected option is built
  from that query rather than found in the current page of options -- otherwise
  a search that excludes it blanks the picker.
- That option is pushed back into the options (`withSelected`), because MUI
  drops a value it cannot find among them.
- `selectOnFocus` is on, so typing replaces the rack's name instead of appending
  to it and matching nothing.

The URL owns the selection (`/racks?rack=bru01-ra`), which makes an elevation a
shareable link.

Panels reach Infrahub from the browser through the Backstage `proxy` plugin,
which injects the API token. Each finds its Infrahub node through the
`infrahub.opsmill.com/id` annotation the provider puts on every entity, which is
why they work for any service kind.

### Branch awareness

The sidebar carries an Infrahub branch picker. Changing it re-queries every
panel and page, and the choice is remembered in `localStorage`. Two details
matter:

- The branch list is always asked of `main`. Asking a deleted branch for the
  list of branches fails, and then nothing could recover the selection — so the
  picker also resets to `main` when the stored branch is no longer there.
- The **catalog is always main**. Entities, their descriptions and the
  pending/live distinction come from the provider polling main; the picker only
  steers live queries. Backstage answers "what exists", Infrahub answers "what
  is changing".

### Gotchas

- **Filters are predicate objects, not strings.** In a filter string a comma
  means OR, so `'kind:resource,spec.type:infrahub-site'` puts the site map on
  every resource. `{ kind: 'resource', 'spec.type': 'infrahub-site' }` ANDs.
- **Colours come from the theme.** Reading `theme.palette` keeps a graph legible
  in both themes; hard-coded white is invisible in the dark one.
- **Traversal depth is the readability dial.** From a service, depth 1 gives 6
  nodes, depth 2 gives 13, depth 3 gives 71 as it fans out through the site. The
  trace uses depth 2 and drops paths that reach a device through the site.
- **`type: 'info'` puts a card beside About**; `'content'` puts it at the bottom
  of the page, under the relations graph.
- **A named page in a module gets no nav item.** It registers fine — the
  visualizer shows it — but the sidebar entry has to be added by hand.
- **A React context from `AppRootWrapperBlueprint` does not apply**, so every
  consumer silently falls back to the default value. The branch store is a
  module-level store with listeners instead, which does not care where anything
  is mounted.

### Tests

`yarn test` covers the GraphQL client's error and timeout handling, the branch
store, the prefix arithmetic (including octet boundaries and the top of the
address space), rack capacity, the trace graph's via-site rule, and the
provider's mapping, template generation and collision warning. The panels
themselves are thin renderers over those functions, which is why the logic is
extracted rather than inlined.

## Things worth knowing

A service node is branch agnostic, so a request appears in the catalog on the
next poll, but its branch aware fields — bandwidth, IP package, and everything
the generator allocates — read as null on `main` until the proposed change is
merged. Those services are tagged `pending-change` and marked
`lifecycle: experimental`, and their form prefill carries only the fields
Infrahub can already read.

A change stacked on a request that has not merged is accepted by Infrahub and
then silently discarded: a service created directly on `main` takes a change on
a branch, while one whose `implement_*` branch is still open does not. So a
service with an open proposed change sends its pencil to that proposed change,
which is where a pending request is actually edited, and only a live service
gets the change form.

Ingested entities are provider-owned and cannot be edited in Backstage: the next
poll overwrites any local change. The pencil icon on a service therefore opens
the template in change mode, prefilled from `?formData=`; on a site or a device
it opens the object in Infrahub, which is the only place those can be edited.

The location dropdown is an `EntityPicker` over the ingested sites, so it follows
Infrahub. Because Backstage lowercases entity names and Infrahub's human friendly
id is case-sensitive, the change template reads the real identifier off the entity
with `catalog:fetch` rather than using the entity name.

Provided APIs, Consumed APIs, Depends on components and Has subcomponents stay
empty on a service: Infrahub models network services, not software APIs, and the
things a service depends on are Resources, which is why `Depends on resources` is
the card that fills.

Every device is placed in its site's rack in `data/08_device.yml` (`rack`,
`position`, `rack_face`), and `data/02_racks.yml` loads before it so those
references resolve. The elevations are therefore there on a fresh install rather
than depending on mutations someone ran once.

Graph nodes deep-link to their Infrahub object, built from the entity's own
`backstage.io/view-url` so the browser-facing address is never configured twice.
