import os
import json
from openai import OpenAI
from apify_client import ApifyClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
apify_client = ApifyClient(os.getenv("APIFY_API_TOKEN"))

def get_agent_configuration(user_request):
    """
    Agentic Step: Analyzes the user request and generates 
    optimal parameters for the Apify Website Content Crawler.
    """
    system_prompt = """
    You are an expert Web Scraping Agent. Your goal is to configure the 'apify/website-content-crawler' actor 
    to fetch the LATEST news articles from a requested site.

    Based on the user's request, output a JSON object with these parameters:
    - "startUrls": A list of objects [{"url": "..."}] derived from the request.
    - "globPatterns": A list of strings. BE PERMISSIVE. 
      Examples: ["/article/**", "/news/**", "/202*/**", "/**/story/**"]. 
      If the site is generic, use ["/**"] to ensure we don't miss links, but try to target article structures if obvious.
    - "maxCrawlPages": Integer. Set this to 10 to ensure we get a good batch of headlines.
    
    IMPORTANT: Return ONLY valid JSON. No markdown formatting.
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Request: {user_request}"}
        ],
        temperature=0.1
    )
    
    try:
        config_str = response.choices[0].message.content.strip()
        if config_str.startswith("```"):
            config_str = config_str.strip("```json").strip("```")
        return json.loads(config_str)
    except Exception as e:
        print(f"Agent Logic Error: {e}")
        return None

def run_scraping_job(config):
    """
    Execution Step: Sends the agent-generated config to Apify.
    """
    # Define ROBUST settings for dynamic news sites
    actor_input = {
        # CRITICAL FIX: Use Playwright to render JS-heavy news sites
        "crawlerType": "playwright:firefox", 
        "initialConcurrency": 2,
        "maxConcurrency": 5,
        "proxyConfiguration": {"useApifyProxy": True},
        
        # Ensure we keep the content
        "saveHtml": True, 
        "saveMarkdown": True,
        
        # Remove clutter to help the AI Agent parse titles better later
        "removeCookieWarnings": True,
        "clickElements": "button, a[href]", # Try to click "load more" or links
    }
    
    # Merge agent config with defaults
    actor_input.update(config)
    
    print(f"🚀 Agent starting scraper with Playwright on: {actor_input.get('startUrls')}")
    
    # Run the Actor
    run = apify_client.actor("apify/website-content-crawler").call(run_input=actor_input)
    
    # Fetch results from the default dataset
    dataset_items = apify_client.dataset(run["defaultDatasetId"]).list_items().items
    return dataset_items
