# Components V2 — what hikari can actually build

Discord's component surface and hikari's builder surface are **not the same
set**. Discord shipped a lot in 2025–2026 that hikari has never implemented.
Design against this file, not against `docs.discord.com`.

Verified against hikari source at tags **2.3.5** (what we run) and **2.5.0**
(latest), 2026-08-02.

## Good news: V2 is fully available at 2.3.5

Components V2 landed wholesale in **hikari 2.3.0** (2025-04-22, *"Add components
V2 (UIKit) support"*). Nothing about V2 changed in 2.4.0, 2.4.1 or 2.5.0.
**Upgrading buys zero V2 capability.**

Every builder this repo imports exists at 2.3.5, in
`hikari.impl.special_endpoints` and re-exported via `hikari.impl`:

`MessageActionRowBuilder`, `TextSelectMenuBuilder`, `SelectMenuBuilder`,
`SelectOptionBuilder`, `ContainerComponentBuilder`, `SectionComponentBuilder`,
`InteractiveButtonBuilder`, `LinkButtonBuilder`, `TextDisplayComponentBuilder`,
`SeparatorComponentBuilder`, `ThumbnailComponentBuilder`,
`MediaGalleryComponentBuilder`, `MediaGalleryItemBuilder`,
`ModalActionRowBuilder`, `TextInputBuilder`, `ChannelSelectMenuBuilder`,
**`FileComponentBuilder`** (available, currently unused).

Not exported at hikari top level — `hikari.ContainerComponentBuilder` fails.
Always import from `hikari.impl`.

Nesting rules, from `api/special_endpoints.py`:

```
ContainerBuilderComponentsT = MessageActionRow | TextDisplay | Section
                            | MediaGallery | Separator | File
SectionBuilderAccessoriesT  = Button | Thumbnail
SectionBuilderComponentsT   = TextDisplay
```

`Thumbnail` is **only** legal as a Section accessory, never a direct Container
child. Containers cannot nest Containers.

## The V2 flag is automatic — for GatewayBot

`RESTClientImpl._build_message_payload` ORs in `IS_COMPONENTS_V2` (`1 << 15`)
whenever any component's type is in `{SECTION, TEXT_DISPLAY, THUMBNAIL,
MEDIA_GALLERY, FILE, SEPARATOR, CONTAINER}` — deliberately excluding
`ACTION_ROW`, so a bare action row does not trip it. This is why the repo sets
the flag nowhere and still works.

It is **not** auto-set on the `InteractionMessageBuilder.build()` path
(RESTBot / interaction-server). We are a `GatewayBot`, so we are on the auto
path.

⚠️ hikari has **no client-side guard** against mixing `content=` with V2
components. It will happily build a payload Discord rejects with 400. Omit
`content` / `embed` yourself.

## THE HARD LIMIT: modals are text-input only

**`ModalActionRowBuilderComponentsT = TextInputBuilder`** — that is the entire
allowed set, at 2.3.5 *and* at 2.5.0.

**`LabelComponentBuilder` does not exist in any hikari version.** Discord's
`LABEL` component (type 18) is simply unimplemented. Confirmed by grepping both
tags: zero matches for any Label builder class.

This matters more than it looks, because Discord requires **selects in modals to
be Label-wrapped**. No Label builder therefore means:

| Discord supports (date shipped) | Reachable from hikari? |
|---|---|
| Text Input in modal | ✅ yes |
| String Select in modal (Aug 2025) | ❌ **no** |
| User/Role/Mentionable/Channel Select in modal (Sep 2025) | ❌ **no** |
| Text Display in modal (Sep 2025) | ❌ **no** |
| File Upload in modal (Oct 2025) | ❌ **no** |
| Radio Group / Checkbox Group / Checkbox (Feb 2026) | ❌ **no** |

**Consequence for design:** the "one modal captures every filter axis in a
single atomic submit" pattern is **not buildable on this stack**. Any research
or tutorial recommending it is describing the raw Discord API, not hikari.

Multi-axis filtering must therefore use **select menus on a message** (one
interaction per axis), with modals reserved for **free-text input only** — which
is exactly what they are used for today in `close.py`'s custom-denial flow.

## Related

- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — why we are on
  2.3.5, and why upgrading is a coupled hikari+lightbulb move.
- [component-dispatcher.md](component-dispatcher.md) — lightbulb's own `Menu`
  has **no** V2 support at any version, which is why the custom dispatcher
  exists.
