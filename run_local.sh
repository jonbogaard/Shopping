#!/bin/bash
# Run local price scraper (Woolly) using the venv
# This wrapper script is called by launchd
cd /Users/jbogaard/Documents/shopping
source .venv/bin/activate
python3 local_scrape.py >> logs/local_scrape.log 2>> logs/local_scrape_error.log
