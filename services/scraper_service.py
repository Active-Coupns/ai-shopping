import logging
import httpx
from typing import List, Dict, Any
from config import settings

logger = logging.getLogger("gateway.scraper")

# Mock e-commerce data generation helper for testing/fallback when API keys are absent
def generate_mock_products(query: str, country: str) -> List[Dict[str, Any]]:
    logger.info(f"Generating mock scraper data for query: '{query}' in {country}")
    
    q_lower = query.lower()
    is_in = (country == "IN")
    category = "generic"
    if "laptop" in q_lower or "computer" in q_lower or "macbook" in q_lower:
        category = "laptop"
    elif "phone" in q_lower or "mobile" in q_lower or "iphone" in q_lower or "samsung" in q_lower:
        category = "phone"
    elif "shoe" in q_lower or "sneaker" in q_lower or "running" in q_lower:
        category = "shoes"
    elif "watch" in q_lower or "smartwatch" in q_lower:
        category = "watch"

    if category == "laptop":
        base_price = 45000 if is_in else 600
        items = [
            {"brand": "Dell", "name": "Inspiron 15", "rating": 4.3, "price_mult": 1.0},
            {"brand": "HP", "name": "Pavilion 14 Aero", "rating": 4.5, "price_mult": 1.25},
            {"brand": "Apple", "name": "MacBook Air M2", "rating": 4.8, "price_mult": 1.8},
            {"brand": "Lenovo", "name": "IdeaPad Slim 3", "rating": 4.1, "price_mult": 0.85},
            {"brand": "ASUS", "name": "Vivobook 15", "rating": 4.2, "price_mult": 0.95},
        ]
    elif category == "phone":
        base_price = 15000 if is_in else 250
        items = [
            {"brand": "Samsung", "name": "Galaxy A54", "rating": 4.4, "price_mult": 1.4},
            {"brand": "Apple", "name": "iPhone 15", "rating": 4.7, "price_mult": 3.2},
            {"brand": "OnePlus", "name": "Nord CE 3", "rating": 4.3, "price_mult": 1.2},
            {"brand": "Motorola", "name": "Moto G84", "rating": 4.2, "price_mult": 0.8},
            {"brand": "Google", "name": "Pixel 7a", "rating": 4.5, "price_mult": 1.8},
        ]
    elif category == "shoes":
        base_price = 3000 if is_in else 50
        items = [
            {"brand": "Nike", "name": "Air Zoom Pegasus", "rating": 4.6, "price_mult": 2.4},
            {"brand": "Adidas", "name": "Ultraboost Light", "rating": 4.7, "price_mult": 3.0},
            {"brand": "Puma", "name": "Velocity Nitro 2", "rating": 4.4, "price_mult": 1.8},
            {"brand": "Reebok", "name": "Floatride Energy 5", "rating": 4.2, "price_mult": 1.5},
            {"brand": "ASICS", "name": "Gel-Kayano 30", "rating": 4.8, "price_mult": 3.2},
        ]
    elif category == "watch":
        base_price = 5000 if is_in else 80
        items = [
            {"brand": "Apple", "name": "Watch SE", "rating": 4.6, "price_mult": 3.0},
            {"brand": "Samsung", "name": "Galaxy Watch 6", "rating": 4.5, "price_mult": 2.8},
            {"brand": "Amazfit", "name": "GTR 4", "rating": 4.3, "price_mult": 1.6},
            {"brand": "Fitbit", "name": "Versa 4", "rating": 4.1, "price_mult": 1.8},
            {"brand": "Garmin", "name": "Venu Sq 2", "rating": 4.4, "price_mult": 2.2},
        ]
    else:
        base_price = 2000 if is_in else 30
        items = [
            {"brand": "GenericCorp", "name": "Super Product Alpha", "rating": 4.0, "price_mult": 1.0},
            {"brand": "PremiumBrand", "name": "Elite Product Beta", "rating": 4.6, "price_mult": 2.5},
            {"brand": "BudgetChoice", "name": "Value Product Gamma", "rating": 3.8, "price_mult": 0.6},
            {"brand": "EcoFriendly", "name": "Green Product Delta", "rating": 4.2, "price_mult": 1.4},
            {"brand": "Innovators", "name": "Future Product Epsilon", "rating": 4.5, "price_mult": 2.0},
        ]

    products = []
    stores = [("Amazon", "amazon.com" if not is_in else "amazon.in")]
    if is_in:
        stores.append(("Flipkart", "flipkart.com"))
    else:
        stores.append(("Walmart", "walmart.com"))

    for idx, item in enumerate(items):
        store_name, store_domain = stores[idx % len(stores)]
        price_val = round(base_price * item["price_mult"], 2)
        
        if store_name == "Amazon":
            url = f"https://www.{store_domain}/dp/B00MOCK{idx:03d}"
        elif store_name == "Walmart":
            url = f"https://www.{store_domain}/ip/MockProduct-{idx:03d}/12345678"
        else: # Flipkart
            url = f"https://www.{store_domain}/mock-product-{idx:03d}/p/itm12345678"

        products.append({
            "title": f"{item['brand']} {item['name']} - Curation Choice ({query})",
            "price": price_val,
            "original_url": url,
            "source": store_name,
            "rating": item["rating"],
            "raw_details": f"Brand: {item['brand']}. Ideal for users looking for high quality {category} in {country}. Evaluated rating is {item['rating']}/5."
        })
        
    return products

import asyncio

async def _execute_hasdata_scrape(query: str, country: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=4.0) as client:
        headers = {
            "x-api-key": settings.HASDATA_API_KEY,
            "Content-Type": "application/json"
        }
        
        scraped_products = []
        is_in = (country == "IN")
        
        amazon_domain = "www.amazon.in" if is_in else "www.amazon.com"
        second_store = "Flipkart" if is_in else "Walmart"
        second_domain = "flipkart.com" if is_in else "walmart.com"
        
        # 1. Fetch from Amazon Search API (Page 1 only for fast caching/scraping)
        try:
            logger.info(f"Calling HasData Amazon Search Scraper for {amazon_domain}")
            params = {
                "q": query,
                "amazon_domain": amazon_domain,
                "delivery_country": country,
                "page": 1
            }
            response = await client.get(
                "https://api.hasdata.com/scrape/amazon/search",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("searchResults") or data.get("results") or []
                for item in results[:5]:
                    price_str = item.get("price") or "0.0"
                    price_val = 0.0
                    try:
                        clean_price = "".join(c for c in str(price_str) if c.isdigit() or c == ".")
                        price_val = float(clean_price) if clean_price else 0.0
                    except ValueError:
                        pass
                        
                    scraped_products.append({
                        "title": item.get("title") or item.get("name"),
                        "price": price_val,
                        "original_url": item.get("url") or item.get("link"),
                        "source": "Amazon",
                        "rating": float(item.get("rating") or 4.0),
                        "raw_details": f"Amazon Product. ASIN: {item.get('asin')}. Rating: {item.get('rating')}. Reviews: {item.get('reviewsCount')}."
                    })
            else:
                logger.error(f"HasData Amazon API returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error occurred calling HasData Amazon Search: {str(e)}")
            
        # 2. Fetch from second store (Walmart or Flipkart) via Google SERP API (Page 1 only)
        try:
            logger.info(f"Calling HasData Google SERP Scraper for {second_store}")
            serp_query = f"site:{second_domain} {query}"
            params = {
                "q": serp_query,
                "location": "India" if is_in else "United States",
                "page": 1
            }
            response = await client.get(
                "https://api.hasdata.com/scrape/google/serp",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("organicResults") or data.get("organic") or []
                for item in results[:5]:
                    scraped_products.append({
                        "title": item.get("title"),
                        "price": 0.0,
                        "original_url": item.get("link") or item.get("url"),
                        "source": second_store,
                        "rating": 4.0,
                        "raw_details": item.get("snippet") or ""
                    })
            else:
                logger.error(f"HasData Google SERP API returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error occurred calling HasData Google SERP: {str(e)}")
            
        return scraped_products

async def scrape_products(query: str, country: str) -> List[Dict[str, Any]]:
    """Scrapes products from country-aware target e-commerce platforms using HasData API.
    
    Enforces a strict 5-second timeout, instantly falling back to local pre-structured JSON results on timeout or failure.
    """
    if not settings.HASDATA_API_KEY:
        logger.warning("HASDATA_API_KEY not configured. Falling back to Mock Scraper Engine.")
        return generate_mock_products(query, country)
        
    try:
        scraped = await asyncio.wait_for(_execute_hasdata_scrape(query, country), timeout=5.0)
        if not scraped:
            logger.warning("Scraper API calls returned no results. Falling back to mock data.")
            return generate_mock_products(query, country)
        return scraped
    except asyncio.TimeoutError:
        logger.error("HasData scraping exceeded strict 5.0 second timeout limit. Falling back to mock data.")
        return generate_mock_products(query, country)
    except Exception as e:
        logger.error(f"Error occurred calling HasData APIs: {str(e)}. Falling back to mock data.")
        return generate_mock_products(query, country)
