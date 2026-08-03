from .woolly import scrape_woolly
from .uniqlo import scrape_uniqlo
from .nike import scrape_nike

# Levi's is handled via deal aggregation (levis_deals.py + levis_gmail.py)
# not direct scraping (Akamai blocks all automated access)

SCRAPER_MAP = {
    "woolly": scrape_woolly,
    "uniqlo": scrape_uniqlo,
    "nike": scrape_nike,
}
