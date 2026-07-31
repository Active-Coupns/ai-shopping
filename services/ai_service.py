import logging
import json
import re
from typing import List, Dict, Any
from openai import AsyncOpenAI
from config import settings

logger = logging.getLogger("gateway.ai")

# 1. OPTIMIZE SEARCH QUERY
async def optimize_search_query(user_query: str, country: str) -> str:
    """Takes raw user query (informal, conversational, or mixed language/hinglish) and optimizes it for scrapers.
    
    Falls back to regex-based cleaning if OpenAI key is missing.
    """
    if not settings.OPENAI_API_KEY:
        logger.info(f"OPENAI_API_KEY not configured. Running Mock Query Optimization for: '{user_query}'")
        query_lower = user_query.lower().strip()
        cleaned = query_lower
        
        # Mixed/Hinglish translations mapping for e-commerce
        translations = {
            "sasta": "budget",
            "sabse sasta": "cheapest",
            "accha": "best quality",
            "acha": "best quality",
            "achha": "best quality",
            "dikhao": "",
            "chahiye": "",
            "under": "under",
            "phone": "smartphone",
            "gaming laptop under 1200": "gaming laptop under 1200",
            "ultraboot shoes": "ultraboot shoes",
            "flagship phone under 50000": "flagship phone under 50000"
        }
        
        for k, v in translations.items():
            cleaned = re.sub(rf"\b{k}\b", v, cleaned)
            
        cleaned = " ".join(cleaned.split())
        return cleaned or user_query

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        system_prompt = (
            "You are an e-commerce search query optimizer. Your job is to convert raw, conversational, "
            "and mixed-language user requests (such as Hinglish or informal text) into a clean, "
            "standardized, and concise e-commerce search query optimized for scraping. "
            "Respond ONLY with the optimized query string. Do not include quotes, explanations, or JSON."
        )
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: \"{user_query}\"\nCountry: {country}"}
            ],
            temperature=0.1,
            max_tokens=50
        )
        
        optimized = response.choices[0].message.content.strip().replace('"', '')
        logger.info(f"Optimized Query: '{user_query}' -> '{optimized}'")
        return optimized
    except Exception as e:
        logger.error(f"Error optimizing search query: {str(e)}")
        return user_query

# 2. CURATE PRODUCTS
def generate_mock_ai_curation(query: str, products: List[Dict[str, Any]], country: str = "US") -> List[Dict[str, Any]]:
    logger.info(f"Running Mock AI Curation for query: '{query}'")
    
    sorted_products = sorted(products, key=lambda x: x.get("rating", 4.0), reverse=True)
    top_picks = sorted_products[:3]
    
    curated_results = []
    for idx, prod in enumerate(top_picks):
        title = prod["title"]
        price = prod["price"]
        source = prod["source"]
        
        specs = {}
        if "laptop" in title.lower() or "macbook" in title.lower():
            specs = {
                "Processor": "Intel i5 / Apple M2" if "Apple" in title else "AMD Ryzen 5",
                "RAM": "16GB LPDDR5" if idx < 2 else "8GB Unified",
                "Storage": "512GB NVMe SSD" if idx == 0 else "256GB SSD",
                "Display": "15.6-inch FHD" if "Dell" in title or "Vivobook" in title else "13.6-inch Liquid Retina"
            }
        elif "phone" in title.lower() or "galaxy" in title.lower() or "iphone" in title.lower():
            specs = {
                "Screen": "6.1-inch OLED" if "Apple" in title else "6.4-inch AMOLED",
                "Camera": "48MP Dual" if "Apple" in title or "Samsung" in title else "50MP Main",
                "Battery": "3200 mAh" if "Apple" in title else "5000 mAh",
                "RAM/Storage": "8GB RAM / 128GB Storage"
            }
        elif "shoe" in title.lower() or "pegasus" in title.lower() or "ultraboot" in title.lower():
            specs = {
                "Type": "Neutral Cushioning",
                "Weight": "9.8 oz (Size 9)",
                "Midsole": "Zoom Air" if "Nike" in title else "Boost Foam"
            }
        else:
            specs = {
                "Features": "Durable Build",
                "Warranty": "1 Year Manufacturer Warranty",
                "Quality": "High grade components"
            }
            
        curr_symbol = "$"
        sentence_1 = f"This {prod['source']} option is selected because its price of {curr_symbol}{price:,.2f} aligns perfectly with your query '{query}'."
        sentence_2 = f"With a user rating of {prod.get('rating', 4.0)}/5, it represents a highly recommended, robust choice that balances features and durability."
        why_fits = f"{sentence_1} {sentence_2}"
        
        curated_results.append({
            "title": re.sub(r"\s*-\s*Curation Choice.*", "", title),
            "price": price,
            "original_url": prod["original_url"],
            "affiliate_url": prod["original_url"],
            "source": source,
            "formatted_specs": specs,
            "why_it_fits_you": why_fits,
            "image_url": prod.get("image_url"),
            "thumbnail": prod.get("thumbnail")
        })
        
    return curated_results

async def curate_products(scraped_items: list, user_query: str) -> list:
    """Curates, filters, and formats e-commerce products using OpenAI GPT-4o-mini.
    
    Selects the top 3 matches, extracts key specifications, and writes a personalized 2-sentence summary.
    Falls back to mock curation if api key is missing or calls fail.
    """
    # Detect country context based on item source / price values if needed, otherwise default to US
    country = "IN" if any(".in" in str(x.get("original_url", "")) or x.get("source") == "Flipkart" for x in scraped_items) else "US"

    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not configured. Falling back to Mock AI Curation Engine.")
        return generate_mock_ai_curation(user_query, scraped_items, country)
        
    if not scraped_items:
        logger.warning("No products provided for curation. Returning empty list.")
        return []

    formatted_input = []
    for idx, p in enumerate(scraped_items):
        formatted_input.append(
            f"ID: {idx}\nTitle: {p['title']}\nPrice: {p['price']}\nStore: {p['source']}\nURL: {p['original_url']}\nRaw Details: {p.get('raw_details', '')[:100]}\n"
        )
    products_context = "\n---\n".join(formatted_input)

    system_prompt = (
        "You are an AI Shopping curation engine. Select the top 3 best matching products from the list.\n"
        "Rules:\n"
        "1. Keep product titles clean and concise, stripping out artificial dynamic text like '- Curation Choice (...)'.\n"
        "2. Ensure the store/vendor name in the 'why_it_fits_you' explanation matches the product source exactly (e.g. refer to Amazon India or Flipkart if that is the source, NEVER refer to Walmart or unrelated stores unless explicitly present in the input product's source).\n"
        "3. Use the exact price values and currency symbol (e.g. ₹ or $) present in the input. Construct insights strictly using the actual scraped titles, prices, and vendor stores. Never invent or convert prices.\n"
        "For each product, extract key specs (formatted_specs) and write a 1-sentence reason ('why_it_fits_you') directly answering the user's request.\n"
        "Respond ONLY with a JSON object in this structure:\n"
        "{\n"
        "  \"picks\": [\n"
        "    {\n"
        "      \"original_id\": <number>,\n"
        "      \"title\": \"<short title>\",\n"
        "      \"price\": <number>,\n"
        "      \"source\": \"<store>\",\n"
        "      \"original_url\": \"<url>\",\n"
        "      \"formatted_specs\": { \"Key\": \"Value\" },\n"
        "      \"why_it_fits_you\": \"<1-sentence reason>\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = (
        f"User Query: \"{user_query}\"\n"
        f"Country: {country}\n"
        f"Products:\n{products_context}"
    )

    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=400
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        picks = data.get("picks") or []
        
        results = []
        for pick in picks[:3]:
            orig_id = pick.get("original_id")
            orig_url = pick.get("original_url")
            
            if (orig_url is None or orig_url == "") and orig_id is not None and 0 <= orig_id < len(scraped_items):
                orig_url = scraped_items[orig_id]["original_url"]
                
            image_url = None
            thumbnail = None
            if orig_id is not None and 0 <= orig_id < len(scraped_items):
                image_url = scraped_items[orig_id].get("image_url")
                thumbnail = scraped_items[orig_id].get("thumbnail")

            raw_title = pick.get("title") or "Product Title"
            cleaned_title = re.sub(r"\s*-\s*Curation Choice.*", "", raw_title)

            results.append({
                "title": cleaned_title,
                "price": float(pick.get("price") or 0.0),
                "original_url": orig_url or "https://www.example.com",
                "affiliate_url": orig_url or "https://www.example.com",
                "source": pick.get("source") or "E-Commerce Store",
                "formatted_specs": pick.get("formatted_specs") or {},
                "why_it_fits_you": pick.get("why_it_fits_you") or "This product matches your requirements.",
                "image_url": image_url,
                "thumbnail": thumbnail
            })
            
        return results
        
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {str(e)}. Falling back to Mock Curation.")
        return generate_mock_ai_curation(user_query, scraped_items, country)
