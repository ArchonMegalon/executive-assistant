import os, httpx

BROWSERACT_API_KEY = os.environ.get("BROWSERACT_API_KEY")

async def scrape_url(url: str, prompt: str = "Extract main content") -> str:
    """Uses BrowserAct to scrape a dynamically rendered URL."""
    if not BROWSERACT_API_KEY:
        return "Error: BROWSERACT_API_KEY not configured."
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Example payload based on standard scraping APIs
            response = await client.post(
                "https://api.browseract.com/v1/scrape", 
                headers={"Authorization": f"Bearer {BROWSERACT_API_KEY}"},
                json={"url": url, "prompt": prompt}
            )
            response.raise_for_status()
            return response.json().get("content", "No content returned.")
        except Exception as e:
            return f"BrowserAct scraping failed: {str(e)}"
