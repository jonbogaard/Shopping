from .woolly import scrape_woolly
from .uniqlo import scrape_uniqlo
from .levis import scrape_levis
from .nike import scrape_nike

SCRAPER_MAP = {
    "woolly": scrape_woolly,
    "uniqlo": scrape_uniqlo,
    "levis": scrape_levis,
    "nike": scrape_nike,
}
