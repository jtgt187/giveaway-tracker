import sys
import os
import traceback

# Ensure project root is on sys.path for module import
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

def run_one(name, cls_path):
    try:
        mod = __import__(cls_path, fromlist=['*'])
        crawler = getattr(mod, name)()
        results = crawler.extract_giveaways()
        print(f"[SMOKE] {name}: found {len(results)} give-aways")
        for r in results[:3]:
            t = r.get('title', '')
            u = r.get('url', '')
            print(f"  - {t[:60]} => {u}")
        return len(results)
    except Exception:
        print(f"[SMOKE] {name}: FAILED to crawl")
        traceback.print_exc()
        return -1

def main():
    print("Running smoke tests for crawlers...")
    modules = [
        ("GleamfinderCrawler", "crawler.gleamfinder"),
        ("BestOfGleamCrawler", "crawler.bestofgleam"),
    ]
    total = 0
    for cls, modpath in modules:
        n = run_one(cls, modpath)
        if n is not None:
            total += max(0, n)
    print(f"[SMOKE] Total found across test crawlers: {total}")

if __name__ == "__main__":
    main()
