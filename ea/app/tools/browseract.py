import os, httpx

BROWSERACT_API_KEY = os.environ.get("BROWSERACT_API_KEY")

async def scrape_url(url: str) -> str:
    """Uses the BrowserAct API to extract text from a URL."""
    if not BROWSERACT_API_KEY: return "Error: BrowserAct API key missing in .env."
    
    # Generic scraping endpoint 
    api_url = "https://api.browseract.com/api/scrape" 
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            res = await client.post(
                api_url, 
                headers={"Authorization": f"Bearer {BROWSERACT_API_KEY}", "Content-Type": "application/json"},
                json={"url": url, "text_only": True}
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("content") or data.get("text") or str(data)
            return f"Failed to scrape. HTTP {res.status_code}: {res.text}"
        except Exception as e:
            return f"BrowserAct error: {e}"
