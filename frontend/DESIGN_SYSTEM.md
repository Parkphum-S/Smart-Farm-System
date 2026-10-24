# Smart Farm System V.1 — Design System

## Reference direction
Based on the existing reference screens:
- White and very light neutral surfaces
- Fresh farm-green as the primary action and status color
- Rounded cards and controls, restrained shadows, clear spacing
- Dense but organized farm dashboard cards, charts, and sensor summaries
- Mobile-first information hierarchy; keep key farm status visible quickly

## Tokens
`packages/shared/src/design-tokens.ts` is the shared source for color, typography,
spacing, radii, and shadows. Web CSS currently mirrors those values as CSS custom
properties. When implementing Mobile, map the same tokens to React Native styles.

## Accuracy
The current hex values are a visual approximation from screenshots, not verified
brand specifications. Replace them only when original design source values/assets
are available. Do not redesign existing screens; use these tokens to standardize them.

## Accessibility
- Keep text/background contrast readable.
- Do not convey status by color alone; pair with labels/icons.
- Preserve visible keyboard focus and reduced-motion preferences.
- Maintain touch targets suitable for mobile use.
