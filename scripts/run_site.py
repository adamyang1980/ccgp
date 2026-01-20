import argparse
import sys
import os
import logging
from typing import Dict, Any

# Ensure project root is in path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ccgp_sites._registry import get_searcher
from ccgp_core.spider import BaseSpider

def main():
    parser = argparse.ArgumentParser(description="Unified CCGP Scraper")
    parser.add_argument("site", help="Site name (e.g. zhejiang, jiangsu, xinjiang)")
    
    # 1a. Unified Parameters
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)", default=None)
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)", default=None)
    parser.add_argument("--region", help="Region code or name", default=None)
    parser.add_argument("--keywords", nargs="*", help="Keywords to filter", default=[])
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum number of pages to scrape")
    parser.add_argument("--max-results", type=int, default=1000, help="Maximum number of results to scrape")
    
    # 1h. Secondary Filter (Jiangsu default off)
    parser.add_argument("--secondary-filter", action="store_true", help="Enable secondary filtering (default off)")
    
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    try:
        SiteClass = get_searcher(args.site)
    except KeyError:
        print(f"Error: Site '{args.site}' not found in registry.")
        sys.exit(1)
        
    config: Dict[str, Any] = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "region": args.region,
        "keywords": args.keywords,
        "max_pages": args.max_pages,
        "max_results": args.max_results,
        "secondary_filter": args.secondary_filter,
        "resume": args.resume,
        "interactive": not args.non_interactive,
        "verbose": args.verbose
    }
    
    print(f"Initializing spider for site: {args.site}")
    try:
        # Instantiate 
        spider = SiteClass(config)
    except TypeError as e:
        # Fallback for sites not yet refactored to accept config in init
        import traceback
        traceback.print_exc()
        print(f"Error initializing site '{args.site}'. It might not be refactored to support unified config yet.")
        sys.exit(1)
        
    if not isinstance(spider, BaseSpider):
        print(f"Warning: Site '{args.site}' does not inherit from BaseSpider. Run behavior might be inconsistent.")
        # Try to run it if it has a run method
        if hasattr(spider, "run"):
             # Map new config to old args if possible?
             # For now, assume we refactor all.
             pass
    
    success = spider.run()
    if success:
        print("Scraping completed successfully.")
        sys.exit(0)
    else:
        print("Scraping failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
