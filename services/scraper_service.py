import logging
import httpx
import re
from typing import List, Dict, Any
from config import settings
from fastapi import HTTPException

logger = logging.getLogger("gateway.scraper")

def sanitize_query(query: str) -> str:
    """Cleans the incoming user query by removing currency symbols, commas, and non-essential stop words."""
    # Lowercase
    q = query.lower()
    # Remove currency symbols, commas, and &
    q = q.replace("₹", "").replace("$", "").replace(",", "").replace("&", "")
    
    # Remove common non-essential stop words/phrases for e-commerce search
    stop_words = ["best", "for", "and", "a", "an", "the", "with", "buy", "online", "price", "under"]
    for word in stop_words:
        q = re.sub(rf"\b{word}\b", "", q)
        
    # Remove duplicate spaces
    q = " ".join(q.split())
    return q.strip()

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

        img_map = {
            "laptop": "https://images.unsplash.com/photo-1496181130204-755241544e35?w=500",
            "phone": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=500",
            "shoes": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500",
            "watch": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500",
            "generic": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500"
        }
        img_url = img_map.get(category, img_map["generic"])

        products.append({
            "title": f"{item['brand']} {item['name']}",
            "price": price_val,
            "original_url": url,
            "source": store_name,
            "rating": item["rating"],
            "raw_details": f"Brand: {item['brand']}. Ideal for users looking for high quality {category} in {country}. Evaluated rating is {item['rating']}/5.",
            "image_url": img_url,
            "thumbnail": img_url
        })
        
    return products

import asyncio

async def _execute_hasdata_scrape(query: str, country: str) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=25.0) as client:
        headers = {
            "x-api-key": settings.HASDATA_API_KEY,
            "Content-Type": "application/json"
        }
        
        scraped_products = []
        amazon_domain = "www.amazon.in"
        
        # 1. Fetch from Google Shopping via Google SERP API (querying Google Shopping explicitly)
        try:
            logger.info("Calling HasData Google Shopping Scraper")
            params = {
                "q": query,
                "domain": "google.co.in",
                "country": "in",
                "location": "India",
                "tbm": "shop",
                "gl": "in",
                "hl": "en",
                "page": 1
            }
            response = await client.get(
                "https://api.hasdata.com/scrape/google/serp",
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("shoppingResults") or data.get("organicResults") or data.get("results") or []
                for item in results:
                    price_str = str(item.get("price") or "")
                    price_val = 0.0
                    try:
                        clean_price = "".join(c for c in price_str if c.isdigit() or c == ".")
                        if clean_price.count(".") > 1:
                            parts = clean_price.split(".")
                            clean_price = parts[0] + "." + "".join(parts[1:])
                        price_val = float(clean_price) if clean_price else 0.0
                    except Exception:
                        pass
                        
                    # Strict validation: title, positive price, image, and link
                    title = item.get("title") or item.get("name")
                    if not title or not isinstance(title, str) or not title.strip():
                        continue
                    if not price_val or price_val <= 0.0:
                        continue
                    img_list = item.get("images") or []
                    img_url = item.get("thumbnail") or (img_list[0] if img_list else None) or item.get("image")
                    if not img_url or not isinstance(img_url, str) or not img_url.startswith("http"):
                        continue
                    orig_url = item.get("link") or item.get("url") or item.get("productLink")
                    if not orig_url or not isinstance(orig_url, str) or not orig_url.startswith("http"):
                        continue
                        
                    scraped_products.append({
                        "title": title,
                        "price": price_val,
                        "original_url": orig_url,
                        "source": "Flipkart",
                        "rating": float(item.get("rating") or 4.0),
                        "raw_details": item.get("snippet") or f"Google Shopping Item from {item.get('source') or 'Flipkart'}",
                        "image_url": img_url,
                        "thumbnail": img_url
                    })
            else:
                logger.error(f"HasData Google Shopping API returned status {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Error occurred calling HasData Google Shopping SERP: {str(e)}")
            
        # 2. If Google Shopping returns zero results, retry with Amazon Search Scraper
        if not scraped_products:
            logger.info("Google Shopping returned zero results. Retrying with Amazon India Scraper.")
            try:
                logger.info(f"Calling HasData Amazon Search Scraper for {amazon_domain}")
                params = {
                    "q": query,
                    "amazon_domain": amazon_domain,
                    "delivery_country": "IN",
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
                    for item in results:
                        price_str = str(item.get("price") or "")
                        price_val = 0.0
                        try:
                            clean_price = "".join(c for c in price_str if c.isdigit() or c == ".")
                            if clean_price.count(".") > 1:
                                parts = clean_price.split(".")
                                clean_price = parts[0] + "." + "".join(parts[1:])
                            price_val = float(clean_price) if clean_price else 0.0
                        except Exception:
                            pass
                            
                        # Strict validation: title, positive price, image, and link
                        title = item.get("title") or item.get("name")
                        if not title or not isinstance(title, str) or not title.strip():
                            continue
                        if not price_val or price_val <= 0.0:
                            continue
                        img_url = item.get("image") or item.get("imageUrl") or item.get("thumbnail")
                        if not img_url or not isinstance(img_url, str) or not img_url.startswith("http"):
                            continue
                        orig_url = item.get("url") or item.get("link")
                        if not orig_url or not isinstance(orig_url, str) or not orig_url.startswith("http"):
                            continue
                            
                        scraped_products.append({
                            "title": title,
                            "price": price_val,
                            "original_url": orig_url,
                            "source": "Amazon",
                            "rating": float(item.get("rating") or 4.0),
                            "raw_details": f"Amazon Product. ASIN: {item.get('asin')}. Rating: {item.get('rating')}. Reviews: {item.get('reviewsCount')}.",
                            "image_url": img_url,
                            "thumbnail": img_url
                        })
                else:
                    logger.error(f"HasData Amazon API returned status {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Error occurred calling HasData Amazon Search: {str(e)}")
                
        return scraped_products[:6]

async def scrape_products(query: str, country: str) -> List[Dict[str, Any]]:
    """Scrapes products from country-aware target e-commerce platforms using HasData API.
    
    Enforces a strict 25-second timeout, raising HTTPException on timeout or empty results.
    """
    sanitized = sanitize_query(query)
    if not settings.HASDATA_API_KEY:
        logger.warning("HASDATA_API_KEY not configured. Falling back to Mock Scraper Engine.")
        return generate_mock_products(sanitized, country)
        
    try:
        scraped = await asyncio.wait_for(_execute_hasdata_scrape(sanitized, country), timeout=25.0)
        if not scraped:
            logger.warning("Scraper API calls returned no results.")
            raise HTTPException(status_code=502, detail="Scraping yielded no valid retail results")
        return scraped
    except asyncio.TimeoutError:
        logger.error("HasData scraping exceeded strict 25.0 second timeout limit.")
        raise HTTPException(status_code=504, detail="Scraping service timed out")
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error occurred calling HasData APIs: {str(e)}.")
        raise HTTPException(status_code=502, detail=f"Scraping service error: {str(e)}")
