# scrapehound

A generic, config-driven product scraper that watches many sites and routes
alerts to **per-source Telegram bots**. Runs free on GitHub Actions.

Combines two scrapers into one framework:
- **New Balance 4E shoes** across 6 AU retailers → `shoes` bot (price-drop alerts)
- **DigiDirect preloved Leica** → `leica` bot (new / removed / price-change alerts)

## How it works

```
config/sources.yaml  ──►  adapter (by type)  ──►  Product[]  ──►  diff vs state  ──►  bot (by name)
config/bots.yaml          shopify / magento_graphql / sfcc_jsonld / browser
```

Each **source** declares a `type` (which adapter), a `bot` (routing), a `notify`
mode, and an optional `filter`. Each **bot** maps to a token/chat env var pair.

Adapters, cheapest method first:

| type | how | used by |
|---|---|---|
| `magento_graphql` | Magento GraphQL API | The Athlete's Foot |
| `shopify` | `/products.json` + `.js` (browser mode for Cloudflare) | Active Feet, Running Co, Brand House Direct |
| `sfcc_jsonld` | search → PDP JSON-LD (extruct) | Rebel Sport |
| `browser` | rendered page + CSS selectors (patchright) | New Balance AU, DigiDirect Leica |

## Setup

```bash
uv sync
cp .env.example .env        # fill SHOES_/LEICA_ bot tokens + chat ids
```

Per bot: create it via @BotFather, message it once, then find the chat id at
`https://api.telegram.org/bot<TOKEN>/getUpdates`.

## Run

```bash
uv run scrapehound --dry-run            # all sources, print what would send
uv run scrapehound --bot shoes          # only shoe sources
uv run scrapehound --source rebel       # only one source
uv run scrapehound --summary --bot leica
uv run pytest -q
```

## Adding a source

Add a block to `config/sources.yaml` with a `type`, a `bot`, and the adapter's
keys. Any Shopify store needs only `type: shopify` + `base_url`; any rendered
listing page needs `type: browser` + CSS `selectors`. New adapter types are a
file in `src/scrapehound/adapters/` decorated with `@register("type")`.

## GitHub Actions

Two workflows: `leica.yml` (every 10 min, headless) and `shoes.yml` (every 6h,
headful Chrome under xvfb for the Akamai/Cloudflare sites). Add the four bot
secrets in repo settings. Each commits its `state/` back.
