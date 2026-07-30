import json
import logging
import traceback
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import get_db
from schemas.search import SearchRequest, SearchResponse, ProductCuration
from services.auth_service import get_current_client, deduct_wallet_credits
from services.scraper_service import scrape_products
from services.ai_service import curate_products, optimize_search_query
from services.affiliate_service import process_affiliates_and_coupons
from models.usage_log import UsageLog

router = APIRouter(prefix="/v1", tags=["Search"])
logger = logging.getLogger("gateway.router.search")

@router.post("/reveal-coupon", summary="Reveal coupon code and trigger background session ping")
def reveal_coupon(
    store: str,
    url: str,
    code: str,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Performs background session tracking / cookie drop and returns the revealed coupon code."""
    # 1. Log the click/redirection to UsageLog
    try:
        log_entry = UsageLog(
            client_id=client_id if client_id else 1,
            endpoint="/v1/reveal-coupon",
            country="US",
            credits_deducted=0.0,
            request_payload=json.dumps({"store": store, "code": code, "target_url": url}),
            response_status=200
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"Error logging coupon reveal: {str(e)}")
        
    # 2. Return JSON response with coupon code
    return { "status": "success", "coupon_code": code }

@router.post("/search", response_model=SearchResponse, summary="Execute white-labeled e-commerce search")
async def execute_search(
    request: SearchRequest,
    client_auth: tuple = Depends(get_current_client),
    db: Session = Depends(get_db)
):
    """Executes a country-aware product search using a Two-Stage AI pipeline and Smart Hybrid Affiliate conversions.
    
    1. Validates the API key & checks the wallet balance (handled by security dependency).
    2. Deducts 1.0 credit upfront. If any downstream process fails, the database transaction is rolled back.
    3. Stage 1: AI Query Optimization (mixed languages/hinglish cleaned and standardized).
    4. Scraper fetch for targeted country engines.
    5. Stage 2: AI Product Curation (filtering Top 3 matches, specs parsing, reasoning).
    6. Smart Hybrid Affiliate Link conversion & active coupon extraction.
    7. Returns payload and logs transaction metrics.
    """
    client, wallet = client_auth
    payload_str = json.dumps({"query": request.query, "country": request.country})
    
    try:
        # Step 1: Upfront Credit Deduction (Safeguarded by DB transaction rollback)
        updated_wallet = deduct_wallet_credits(db, wallet, amount=1.0)
        
        # Step 2: Stage 1 AI Query Optimization
        optimized_query = await optimize_search_query(request.query, request.country)
        
        # Step 3: HasData Scraper fetch for country
        raw_products = await scrape_products(optimized_query, request.country)
        
        # Step 4: Stage 2 AI Product Curation
        curated_picks = await curate_products(raw_products, request.query)
        
        # Step 5: Smart Hybrid Affiliate Link & Coupon waterfall Conversion
        final_picks, active_coupons = process_affiliates_and_coupons(
            db, 
            curated_picks, 
            request.country,
            client.id
        )
        
        # Step 6: Log usage metrics on success
        log_entry = UsageLog(
            client_id=client.id,
            endpoint="/v1/search",
            country=request.country,
            credits_deducted=1.0,
            request_payload=payload_str,
            response_status=status.HTTP_200_OK
        )
        db.add(log_entry)
        db.commit()
        
        result_payloads = [ProductCuration(**prod) for prod in final_picks]
        return SearchResponse(
            results=result_payloads,
            coupons=active_coupons,
            credits_remaining=updated_wallet.balance
        )
        
    except HTTPException as http_ex:
        db.rollback() # Rollback credit deduction on HTTP errors
        
        log_entry = UsageLog(
            client_id=client.id,
            endpoint="/v1/search",
            country=request.country,
            credits_deducted=0.0,
            request_payload=payload_str,
            response_status=http_ex.status_code
        )
        db.add(log_entry)
        db.commit()
        raise http_ex
        
    except Exception as e:
        db.rollback() # Rollback credit deduction on unhandled errors
        logger.error(f"Unhandled exception in gateway search: {str(e)}\n{traceback.format_exc()}")
        
        log_entry = UsageLog(
            client_id=client.id,
            endpoint="/v1/search",
            country=request.country,
            credits_deducted=0.0,
            request_payload=payload_str,
            response_status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gateway routing failed: {str(e)}"
        )
