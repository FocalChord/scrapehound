.PHONY: install test check list dry run fmt

install:        ## sync deps + browser
	uv sync && uv run patchright install chromium

test:           ## run the test suite
	uv run pytest -q

check:          ## validate config + bot creds
	uv run scrapehound check

list:           ## show configured sources + bots
	uv run scrapehound list

dry:            ## scrape everything, print what would send (no Telegram, no state)
	uv run scrapehound --dry-run

run:            ## scrape everything for real
	uv run scrapehound
