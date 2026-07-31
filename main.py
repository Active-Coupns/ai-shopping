import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from database import engine, Base, SessionLocal, seed_database
from routers.search import router as search_router
from routers.admin import router as admin_router
from routers.dashboard import router as dashboard_router
from routers.client import router as client_router

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gateway.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events manager for the API Gateway.
    
    Performs schema creation, table initialization, and seeds affiliate configurations on startup.
    """
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    # Run dynamic SQLite migrations for Client monetization columns
    db = SessionLocal()
    try:
        from sqlalchemy import text
        migrations = [
            "ALTER TABLE clients ADD COLUMN primary_strategy VARCHAR DEFAULT 'direct';",
            "ALTER TABLE clients ADD COLUMN cuelinks_pub_id VARCHAR;",
            "ALTER TABLE clients ADD COLUMN amazon_tag VARCHAR;",
            "ALTER TABLE clients ADD COLUMN flipkart_tag VARCHAR;",
            "ALTER TABLE clients ADD COLUMN amazon_tag_in VARCHAR;",
            "ALTER TABLE clients ADD COLUMN amazon_tag_us VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN cuelinks_publisher_id VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN amazon_tag_in VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN amazon_tag_us VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN flipkart_subid VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN aggregator_network_name VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN aggregator_publisher_id VARCHAR;",
            "ALTER TABLE affiliate_configs ADD COLUMN aggregator_url_template VARCHAR;"
        ]
        for migration in migrations:
            try:
                db.execute(text(migration))
                db.commit()
            except Exception:
                db.rollback()
    except Exception as e:
        logger.warning(f"Database schema migration warning: {str(e)}")
    finally:
        db.close()
        
    # Run data seeding for affiliate configs
    db = SessionLocal()
    try:
        seed_database(db)
        logger.info("Database initialized and default configurations seeded successfully.")
    except Exception as e:
        logger.error(f"Database seeding failed: {str(e)}")
    finally:
        db.close()
        
    yield
    logger.info("Gateway shutting down...")

# Initialize FastAPI App
app = FastAPI(
    title="Multi-Tenant API Gateway Middleware",
    description="Secure, white-labeled client API Gateway proxy to third-party scraping & AI engines.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def options_preflight_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    response = await call_next(request)
    return response

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Pydantic validation failed for request {request.url.path}: {exc.errors()}\nBody: {exc.body}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY if 'status' in globals() else 422,
        content={"detail": exc.errors(), "body": exc.body}
    )

# Mount Routers
app.include_router(search_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
app.include_router(client_router)

@app.get("/", tags=["Health"])
async def root():
    """Health check and API Gateway status metadata endpoint."""
    return {
        "gateway": "Multi-Tenant API Gateway Middleware",
        "status": "online",
        "version": "1.0.0",
        "supported_markets": ["US", "IN"],
        "endpoints": {
            "search": "POST /v1/search",
            "admin": "POST /admin/*"
        }
    }
