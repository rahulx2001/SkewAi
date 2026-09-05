# Skew AI console — design prompt (lock this system)

Visual source of truth: the attached Claude Console screenshot
`019ffab9-8676-71b1-8ba6-b764d04a2f94/images/image-718f63a4-a33d-4d6f-aa21-9a49784ef657.png`
(Image #1). Later work must restyle **Skew AI** to this language. Do not
rebuild Claude Console (no credits page, no model catalog, no Anthropic
marks, no “Build an agent”).

This file is the token and chrome contract. CSS variables and the shell
must match these rules. If a later change fights this file, this file wins
unless the product owner overrides it.

---

## Team / tone

Calm operator console. Quiet, dense, scannable. Premium comes from
restraint: same-tone surfaces, hairline edges, large figures, almost no
color. It should feel like a senior ops tool someone sits in all day, not a
marketing site and not a teal “AI dashboard.”

Voice: short labels, sentence case, no tracked-out uppercase costume on
every small string. Group labels in the rail may be small and muted; they
are not a second brand face.

## Color

Default theme is **dark**. Image #1 is dark.

| Token | Hex | Role |
| --- | --- | --- |
| `--bg` | `#141413` | Near-black **warm charcoal** field. Not cool teal-slate `#090b10`. |
| `--bg-raised` | `#1a1a18` | Slightly lifted canvas |
| `--bg-panel` | `#1c1c1a` | Card / rail / panel — same family as the field |
| `--bg-hover` | `#262624` | Active nav row and default filled controls |
| `--edge` | `#2c2c29` | Hairline on cards and rail |
| `--edge-strong` | `#3a3a36` | Stronger lip on inputs |
| `--ink` | `#f4f3ef` | Primary text (warm off-white) |
| `--ink-soft` | `#9c9a94` | Secondary |
| `--ink-faint` | `#6e6c67` | Tertiary / rail groups |
| `--accent` | `#d8d4cc` | Quiet stone. **Not** `#2ec4a7`. |
| `--focus` | `#d8d4cc` | Focus ring, tonal |

Semantic status (muted, not neon): `--ok #8aab84`, `--warn #c4a46a`,
`--danger #c97a72`.

Light theme exists as an override, **not** the house look, and **not** the
old teal ops daylight (`#e9eef5` / `#0d9488`). Light field is warm paper
`#f3f1eb`, ink `#1c1b18`, accent `#2a2926`.

No teal glow, no radial accent bloom behind the canvas, no brand-scan
lockup, no cool `#090b10` / `#2ec4a7` house pair.

## Type

House pairing is **not** Sora + IBM Plex Mono.

- `--sans`: self-hosted Geist (“Skew Sans” in CSS), weights 400 / 500 / 600.
- `--mono`: self-hosted Geist Mono, **only** for real data (ids, clocks,
  codes, tabular figures when a mono is needed). Do not set running labels,
  nav, or the greeting in mono.

Greeting and page titles: sans, ~28–34px, weight 500–600, slight negative
tracking, one or two lines. Metric figures: large tabular-nums in the same
sans (or mono only if the figure is a code), weight 560, no cramped
tracking.

Do not load Google Fonts for the identity.

## Look (chrome)

1. **Left rail.** A quiet left rail, same charcoal as the page (or one step). No gradient
   wash, no corner glow. Product wordmark is **text only** — “Skew AI” —
   no icon-in-a-colored-tile, no animated scan line.
2. **Active row.** Slightly lighter rounded rectangle (`--bg-hover`), same
   ink. No left accent bar, no teal wash, no glow border.
3. **Search.** Quiet field in the rail or topbar: “Search or jump” plus a
   small `⌘K` keycap. Opens the existing command palette.
4. **Page-opening greeting** on home / command: time-of-day line
   (“Good morning” / “Good afternoon” / “Good evening”), not a kicker +
   “Command center” stack.
5. **Metric row.** Three or four **same-tone** cards: hairline `--edge`,
   radius ~14px, large tabular figure, small label above, quiet hint
   below. No accent wash on the first card. No colored top bar.
6. **Action buttons.** Default = dark filled (`--bg-hover`) + hairline.
   Primary = warm off-white fill, dark ink (Image #1’s “Build an agent”).
   Ghost = transparent. **No** hover lift / boop. **No** teal fill CTA.
   Image #1’s filled-primary next to a quieter dark button is allowed here.
7. **Resource / jump cards.** Same hairline dark cards as metrics. Title +
   one line of hint. No uppercase accent kicker as the card identity.
8. **Topbar.** Thin, same field, no blur-glow, no teal chip for the build
   stamp. Theme control is a text label (Dark / Light), not a sun–moon pill.

## Feel

Still. Almost no motion. Surfaces do not float. Depth is a 1px self-colored
edge, not a drop shadow bloom. Hover is a one-step tonal shift. Content is
visible by default — never start a page at `opacity: 0` and wait for an
entrance animation.

Quiet chips (status, “Updated”) are allowed when Image #1 uses them. Do not
pepper every noun with a pill.

## Design (layout)

```
[ wordmark ]
[ pack / workspace row ]
[ search ⌘K ]
[ nav groups, active = lighter rounded row ]
[ account / pack foot ]

                 Good afternoon                    [ghost] [dark btn] [white btn]

                 ┌ metric ┐ ┌ metric ┐ ┌ metric ┐ ┌ metric ┐
                 │  12    │ │   0    │ │  40    │ │ READY  │
                 └────────┘ └────────┘ └────────┘ └────────┘

                 ┌ resource card ┐ ┌ resource card ┐ …
```

Existing Skew routes stay: command, voice, live console, cases, insights,
economics, trust, builder, early warning, studio, enterprise, audits,
platform, settings.

## Forbidden slop (this product)

- Sora + IBM Plex Mono as the house pairing
- `#090b10` field, `#2ec4a7` accent, teal glow, animated brand-scan tile
- Cool blue-charcoal / indigo-slate night mode
- Purple / blue-to-purple gradients
- Pill eyebrow over a hero headline
- Grid-paper or faint module grid behind the page
- Card hover-lift + glowing border
- Sun–moon sliding theme switch
- Entrance animations that hide content
- Cloning Claude’s credits / models / API-keys IA or Anthropic marks

## Checkable acceptance

- Default `--bg` is warm near-black (`#141413` family), luminance well
  under a mid-gray; not `#090b10`.
- `--accent` is not `#2ec4a7`; `--sans` is not Sora; `--mono` is not
  IBM Plex Mono.
- No `@keyframes brand-scan` and no teal logo tile.
- Command view opens with a greeting headline and a metric row of
  hairline same-tone cards.
- Light theme tokens still exist and are warm paper, not teal daylight.
