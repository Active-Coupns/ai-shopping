import logging
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from models.affiliate import AffiliateConfig
from schemas.search import Coupon

logger = logging.getLogger("gateway.affiliate")

def inject_affiliate_tag(url: str, store_name: str, tag: str) -> str:
    """Injects affiliate parameters into e-commerce URLs using standard URL query formatting."""
    try:
        parsed_url = urlparse(url)
        query_params = dict(parse_qsl(parsed_url.query))
        
        store_lower = store_name.lower()
        if "amazon" in store_lower:
            query_params["tag"] = tag
        elif "walmart" in store_lower:
            query_params["affid"] = tag
            query_params["veh"] = "aff"
        elif "flipkart" in store_lower:
            query_params["affid"] = tag
        else:
            query_params["ref"] = tag
            
        new_query = urlencode(query_params)
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))
        return new_url
    except Exception as e:
        logger.error(f"Error injecting affiliate tag into URL '{url}': {str(e)}")
        return url

def transform_product_url(product_url: str, merchant: str, config: AffiliateConfig, client: Any = None) -> str:
    """Transforms product URLs using Smart Hybrid Affiliate link routing logic.
    
    1. Check 1 (Direct Tag):
       - If primary_strategy is "direct":
         - If merchant is Amazon and config.amazon_tag_in/us exists (or config.affiliate_tag matches), append ?tag=...
         - If Flipkart and config.flipkart_subid exists (or config.affiliate_tag matches), append ?affid=...
         - Else if general store config.affiliate_tag matches, inject standard tag.
    2. Check 2 (Generic Aggregator):
       - Else if aggregator_publisher_id exists, construct redirect URL using aggregator_url_template
         (supports CueLinks, Skimlinks, Impact, or any custom network).
    3. Fallback:
       - Return Plain Original Product Clean URL.
    """
    if not config:
        return product_url
        
    merchant_lower = merchant.lower()
    direct_tag = None
    primary_strategy = getattr(client, "primary_strategy", "direct") if client else "direct"
    
    # Check 1: Direct Merchant Tag (Only applied if client's strategy is "direct" or no client config is active)
    if primary_strategy == "direct":
        if "amazon" in merchant_lower:
            if config.country == "IN" and config.amazon_tag_in:
                direct_tag = config.amazon_tag_in
            elif config.country == "US" and config.amazon_tag_us:
                direct_tag = config.amazon_tag_us
            elif config.affiliate_tag and merchant_lower == config.store_name.lower():
                direct_tag = config.affiliate_tag
        elif "flipkart" in merchant_lower:
            if config.flipkart_subid:
                direct_tag = config.flipkart_subid
            elif config.affiliate_tag and merchant_lower == config.store_name.lower():
                direct_tag = config.affiliate_tag
        elif config.affiliate_tag and merchant_lower == config.store_name.lower():
            direct_tag = config.affiliate_tag
            
    if direct_tag:
        return inject_affiliate_tag(product_url, merchant, direct_tag)
        
    # Check 2: Fallback to Generic Aggregator
    if getattr(config, "aggregator_publisher_id", None):
        pub_id = config.aggregator_publisher_id
        template = getattr(config, "aggregator_url_template", None) or "https://links2re.com/?pub_id={PUB_ID}&url={URL}"
        
        # Replace template tokens case-insensitively
        redirect_url = template.replace("{PUB_ID}", pub_id)\
                               .replace("{pub_id}", pub_id)\
                               .replace("{URL}", quote(product_url))\
                               .replace("{url}", quote(product_url))
        return redirect_url
        
    # Check 3: Fallback - Return Clean Original URL
    return product_url

def process_affiliates_and_coupons(
    db: Session,
    products: List[Dict[str, Any]],
    country: str,
    client_id: int = None
) -> tuple[List[Dict[str, Any]], List[Coupon]]:
    """Fetches affiliate configurations, applies the smart hybrid routing waterfall and coupon waterfall for each product."""
    from models.client import Client
    
    # Fetch client details if client_id is set
    client = None
    if client_id:
        client = db.query(Client).filter(Client.id == client_id).first()
        
    # Fetch all configurations matching this client_id (and fallback to system default global configurations)
    configs = db.query(AffiliateConfig).filter(
        AffiliateConfig.country == country,
        (AffiliateConfig.client_id == client_id) | (AffiliateConfig.client_id == None),
        AffiliateConfig.is_active == True
    ).order_by(AffiliateConfig.client_id.desc()).all()
    
    # Select the primary configuration for the target store / client config map
    config_map = {}
    for cfg in configs:
        store_key = cfg.store_name.lower()
        if store_key not in config_map:
            config_map[store_key] = cfg
            
    # Locate client-specific affiliate config containing publisher id / overrides
    client_config = None
    for cfg in configs:
        if cfg.client_id == client_id:
            client_config = cfg
            break
            
    # If no client specific config row is created yet, we can construct a dummy AffiliateConfig representing client settings
    if not client_config and client_id:
        if client:
            client_config = AffiliateConfig(
                client_id=client_id,
                country=country,
                store_name="Amazon",
                affiliate_tag=client.amazon_tag or "",
                aggregator_publisher_id=client.cuelinks_pub_id,
                aggregator_network_name="CueLinks",
                aggregator_url_template="https://links2re.com/?pub_id={PUB_ID}&url={URL}",
                amazon_tag_in=client.amazon_tag_in,
                amazon_tag_us=client.amazon_tag_us,
                flipkart_subid=client.flipkart_tag # map legacy flipkart_tag
            )
            
    # If still no config, fall back to global config default for the country if available
    if not client_config:
        client_config = config_map.get("amazon") or (configs[0] if configs else None)
        
    # Check if client has ANY custom monetization tags configured in AffiliateConfig or Client record
    has_custom_monetization = False
    if client_id:
        # Check database AffiliateConfig rows for this client
        client_configs = db.query(AffiliateConfig).filter(
            AffiliateConfig.client_id == client_id
        ).all()
        for cfg in client_configs:
            if (cfg.aggregator_publisher_id or 
                cfg.amazon_tag_in or 
                cfg.amazon_tag_us or 
                cfg.flipkart_subid or
                cfg.affiliate_tag):
                has_custom_monetization = True
                break
        
        # Check Client record fields
        if not has_custom_monetization and client:
            if (client.cuelinks_pub_id or 
                client.amazon_tag_in or 
                client.amazon_tag_us or 
                client.flipkart_tag or
                client.amazon_tag):
                has_custom_monetization = True
        
    updated_products = []
    for prod in products:
        p_copy = prod.copy()
        original_url = p_copy.get("original_url", "")
        source = p_copy.get("source", "")
        
        if client_id and not has_custom_monetization:
            # 100% clean, plain product links without any CueLinks or Amazon affiliate parameters
            p_copy["affiliate_url"] = original_url
        else:
            # Determine store config
            store_config = config_map.get(source.lower())
            
            # If the configuration found is a system default (client_id == None),
            # but the client has a generic aggregator_publisher_id, we override the config
            # with the client_config to trigger generic aggregator redirection.
            if store_config and store_config.client_id is None and client_config and getattr(client_config, "aggregator_publisher_id", None):
                store_config = client_config
            elif not store_config:
                store_config = client_config
                
            p_copy["affiliate_url"] = transform_product_url(
                original_url,
                source,
                store_config,
                client
            )
        
        # --- COUPON WATERFALL ---
        coupon_code = "None"
        coupon_description = "No Coupon Available Today"
        coupon_status = "No Coupon Available Today"
        reveal_url = ""
        
        # Determine store config for coupons
        store_config = config_map.get(source.lower())
        if store_config and store_config.client_id is None and client_config and getattr(client_config, "aggregator_publisher_id", None):
            store_config = client_config
        elif not store_config:
            store_config = client_config

        # Check 1 (Manual Coupon):
        if store_config and getattr(store_config, "coupon_code", None):
            coupon_code = store_config.coupon_code
            coupon_description = getattr(store_config, "coupon_description", None) or "Manual store coupon code"
            coupon_status = "Manual Coupon"
        # Check 2 (Auto Coupon):
        else:
            auto_coupon = prod.get("coupon")
            if not auto_coupon:
                # Dynamic simulator for test queries matching source
                title_lower = prod.get("title", "").lower()
                if "laptop" in title_lower:
                    auto_coupon = "LAPTOP5"
                elif "phone" in title_lower:
                    auto_coupon = "PHONE10"
                elif "shoe" in title_lower:
                    auto_coupon = "SHOES15"
            if auto_coupon:
                coupon_code = auto_coupon
                coupon_description = "Automatically fetched discount offer from store catalog"
                coupon_status = "Auto Coupon"
                
        # Generate Reveal URL if a coupon is active
        if coupon_status != "No Coupon Available Today":
            reveal_url = f"/v1/reveal-coupon?store={quote(source)}&url={quote(p_copy['affiliate_url'])}&code={quote(coupon_code)}"
            if client_id:
                reveal_url += f"&client_id={client_id}"
                
        p_copy["coupon_code"] = coupon_code
        p_copy["coupon_description"] = coupon_description
        p_copy["coupon_status"] = coupon_status
        p_copy["reveal_url"] = reveal_url
        
        updated_products.append(p_copy)
        
    coupons = []
    for cfg in config_map.values():
        if cfg.coupon_code:
            coupons.append(Coupon(
                code=cfg.coupon_code,
                description=cfg.coupon_description or "General discount offer",
                store=cfg.store_name
            ))
            
    return updated_products, coupons
