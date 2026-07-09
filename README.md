# proofrun-demo-app

A deliberately tiny Vite + React storefront used as the target for
[ProofRun](https://github.com/) demos. It ships one seeded bug and a set of
fixtures reachable by query parameter:

| Route | Behavior |
|---|---|
| `/cart?fixture=null-cart` | renders `<CartSummary cart={null}/>` → throws `TypeError: Cannot read properties of null (reading 'total')` |
| `/cart?fixture=ok` | healthy cart, shows `Total: $42.00` |
| `/cart?fixture=layout-shift` | a button visually buried under a banner — looks broken, never throws |

`proofrun.map.json` maps source files to the route that exercises them.

## Run

```bash
npm ci
npm run build && npm run preview   # serves on http://127.0.0.1:4173
npm test                            # baseline Playwright suite (always green)
```
