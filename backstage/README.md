# Otter-net service portal

A Backstage portal over Infrahub, and an alternative front end to this demo's
Streamlit app. The catalog is Infrahub's data rather than a copy of it, and a
request submitted here opens a branch and a proposed change.

Run it from the repository root:

```sh
invoke backstage-install   # once, installs Node dependencies
invoke backstage           # dev server on http://localhost:3001
invoke backstage-test
```

See `dev/guides/backstage.md` for how it is packaged and configured.
