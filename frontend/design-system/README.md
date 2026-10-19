# VTRS design system

`tokens/tokens.json` is the source of truth. `npm run build` (or
`node scripts/build-tokens.mjs`) checks every declared contrast pair, then writes:

| File | Used by |
| --- | --- |
| `tokens/globals.css` | portal: CSS variables for light, War Room (`.war-room`) and admin chrome |
| `tokens/tailwind.preset.ts` | portal: Tailwind v3 preset |
| `tokens/tailwind-v4.css` | Tailwind v4 `@theme` mapping |

Do not edit generated files. Change a token, rebuild, commit the output.

## Where the build differs from the written spec

The contrast gate found two places where the written rules and the numbers disagree. Both are
resolved in `tokens.json`:

1. **Input border.** `ink-400` (`#7C948F`) is 3.24:1 against white but 2.87:1 against the mint
   input fill. WCAG's boundary rule measures against the surface the field sits on (white,
   canvas or card), so the check is against those, and passes. The fill itself is not the
   boundary.
2. **Dark destructive button.** The War Room theme's destructive red is `#CC3338` (5.1:1 with
   white text); a lighter red failed 4.5:1.

Additions the spec did not name, kept to the spec's rules: a `Critical` severity above High
(the platform has four levels, the design names three), shown in red with a siren icon and a
triangle map marker.
