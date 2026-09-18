# Smart onboarding

ASO can discover existing provider and 3X-UI node metadata before a registry row is committed.
The onboarding path is read-only against cloud providers and the Master panel.

Run:

```bash
./asoctl setup
```

For a provider, enter only the provider type, a local provider key/display name, and an API token
(or reuse the configured legacy environment token). ASO validates read access before saving the
provider. Region, server type, and image are learned later from the existing server/instance.

For a node, enter:

- provider key,
- provider server/instance ID,
- existing Master 3X-UI Node ID,
- the current node API token when the Master reports one is configured,
- SSH credential material required for future replacement VPS deployment,
- an optional local ASO node name.

ASO then reads and validates:

- provider server existence/status/public IPv4/region/type/image,
- Master node address/port/basePath/status/Xray state,
- Master-to-node probe connectivity,
- direct node API token connectivity when a token is configured.

The Master address is retained as the monitoring target. The provider public IPv4 is stored
separately as the VPS identity used by destructive-safety checks. This is important when the Master
uses a hostname instead of a literal IP.

## Safety

Smart onboarding never calls provider create/delete/reboot endpoints and never updates the Master.
Discovery must succeed before a Provider/Node row is saved. New credential values are staged under a
candidate secret reference so a failed validation does not overwrite the credential used by an
existing provider record.

If a provider cannot expose one of the replacement-template fields (for example an image on a
custom/ISO-installed VPS), the wizard first reports the missing field and only then offers manual
overrides for the missing region/type/image values. Normal provider-backed nodes do not require
manual entry of those fields.

Replacement template metadata is stored per current VPS/Node, not only as a provider-wide default,
so multiple nodes in one provider account may safely use different regions, plans, or images.
