# scrapehound

A generic, config-driven product scraper that watches many sites and routes
alerts to **per-source Telegram bots**. Runs free on GitHub Actions.

Combines two scrapers into one framework:
- **New Balance 4E shoes** across 6 AU retailers → `shoes` bot (price-drop alerts)
- **DigiDirect preloved Leica** → `leica` bot (new / removed / price-change alerts)

## Onboard your own watcher (60 seconds)

scrapehound is a platform — start a fresh watcher without writing YAML by hand:

```bash
uvx --from git+https://github.com/FocalChord/scrapehound scrapehound init my-watcher
cd my-watcher && uv sync

scrapehound bot deals --token <BOTFATHER_TOKEN>   # message the bot first; chat id auto-found
scrapehound add https://somestore.com.au --bot deals   # auto-detects the platform
scrapehound preview somestore                     # see what it extracts
scrapehound check                                 # validate config + creds
scrapehound --dry-run                             # what it would alert on
```

`init` scaffolds `config/`, `.env`, and a GitHub Actions workflow; `add` detects
Shopify automatically (and scaffolds a `browser` template with TODO selectors for
anything else); `bot` connects a Telegram bot and discovers its chat id. Then
narrow results by adding a `filter` to the source (see the rule ops below) and
push to GitHub with the bot's secrets.

## How it works

Three cleanly separated stages — platform extraction, then domain config:

```
 EXTRACT (adapter)             DERIVE (config)            SELECT (config)
 site → Product[] + variants   compute attrs from         keep items via a
 no domain knowledge           title/variants (brand,     generic rule predicate
                               width, sizes, ...)         over fields/attrs
        │                            │                          │
        └─────────────► diff vs per-source state ──► bot (by name, by mode)
```

A new **product domain** (cameras, GPUs, ...) is pure config (`derive` + `filter`
rules); a new **site platform** is one `@register`ed adapter. Each **source**
declares `type` (adapter), `bot` (routing), `notify` mode, optional `derive`, and
optional `filter` (a list of rules). Each **bot** maps to a token/chat env pair.

```yaml
the_running_company:
  type: shopify
  bot: shoes
  notify: price_drop
  base_url: "https://shop.therunningcompany.com.au"
  prefilter: [[new balance], ["4e", "x-wide"]]      # cheap fetch-time pruning
  derive:
    brand: {from: title, match: [New Balance, Asics]}
    width: {from: title, regex: '\b([2468]E)\b', upper: true}
    sizes_in_stock: {from_variants: Size}
  filter:
    - {attr: brand, op: eq, value: New Balance}
    - {attr: width, op: in, value: ["4E"]}
    - {attr: sizes_in_stock, op: intersects, value: [10, 10.5]}
    - {field: title, op: not_contains, value: [women, work boot]}
```

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
uv run scrapehound                      # all sources: scrape, alert, persist
uv run scrapehound --bot shoes          # only sources routed to a bot
uv run scrapehound --source rebel       # only one source
uv run scrapehound --dry-run            # print what would send; don't persist
uv run scrapehound --summary --bot leica

uv run scrapehound list                 # show sources + bots (and creds status)
uv run scrapehound check                # validate config + creds (use in CI)
uv run scrapehound test-bot shoes       # send a test message to a bot
```

Common tasks are in the `Makefile` too: `make check`, `make list`, `make dry`,
`make test`.

## Adding a source

Add a block to `config/sources.yaml` with a `type`, a `bot`, and the adapter's
keys. Any Shopify store needs only `type: shopify` + `base_url`; any rendered
listing page needs `type: browser` + CSS `selectors`. New adapter types are a
file in `src/scrapehound/adapters/` decorated with `@register("type")`.

## GitHub Actions

Two workflows: `leica.yml` (every 10 min, headless) and `shoes.yml` (every 6h,
headful Chrome under xvfb for the Akamai/Cloudflare sites). Add the four bot
secrets in repo settings. Each commits its `state/` back.
