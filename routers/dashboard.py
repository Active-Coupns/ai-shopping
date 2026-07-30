import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import get_db
from config import settings

from models.client import Client
from models.api_key import ApiKey
from models.wallet import CreditWallet
from models.usage_log import UsageLog
from models.affiliate import AffiliateConfig

from schemas.dashboard import DashboardLoginRequest, DashboardLoginResponse, AffiliateTagUpdateRequest, AffiliateConfigUpdateRequest
from services.auth_service import validate_client_key

router = APIRouter(tags=["Dashboard"])
logger = logging.getLogger("gateway.router.dashboard")

# Dependency to authenticate either via X-API-Key header OR Authorization Bearer token
def get_dashboard_client(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> tuple[Client, CreditWallet]:
    """Authenticates client queries from the frontend dashboard."""
    token = None
    if x_api_key:
        token = x_api_key
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials"
        )
        
    return validate_client_key(token, db)

@router.post("/v1/dashboard/login", response_model=DashboardLoginResponse)
def dashboard_login(payload: DashboardLoginRequest, db: Session = Depends(get_db)):
    """Handles unified dashboard logins for admins and client tenants."""
    # 1. Admin login flow
    if payload.email == "admin@gateway.local":
        if payload.password == settings.ADMIN_API_KEY:
            return DashboardLoginResponse(
                access_token=settings.ADMIN_API_KEY,
                role="admin",
                client_name="Administrator"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Admin Password"
        )
        
    # 2. Client API Key login flow
    if payload.api_key:
        key_record = db.query(ApiKey).filter(ApiKey.key == payload.api_key, ApiKey.is_active == True).first()
        if not key_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or Revoked API Key"
            )
        client = key_record.client
        return DashboardLoginResponse(
            access_token=payload.api_key,
            role="client",
            client_name=client.name
        )
        
    # 3. Client Email/Password login flow
    if payload.email and payload.password:
        client = db.query(Client).filter(Client.email == payload.email).first()
        if not client or client.password != payload.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Client Email or Password"
            )
            
        # Get active API key
        key_record = db.query(ApiKey).filter(ApiKey.client_id == client.id, ApiKey.is_active == True).first()
        if not key_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Client has no active API keys. Please contact Admin."
            )
            
        return DashboardLoginResponse(
            access_token=key_record.key,
            role="client",
            client_name=client.name
        )
        
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Credentials must contain API Key or Email/Password"
    )

@router.get("/v1/dashboard/client/profile")
def get_client_profile(
    client_auth: tuple = Depends(get_dashboard_client),
    db: Session = Depends(get_db)
):
    """Fetches the client profile including wallet, key, custom affiliate tags, and recent usage logs."""
    client, wallet = client_auth
    
    # Get active key
    key_record = db.query(ApiKey).filter(ApiKey.client_id == client.id, ApiKey.is_active == True).first()
    api_key_str = key_record.key if key_record else "No active key"
    
    # Get custom affiliate tags
    affiliates = db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).all()
    aff_tags = {
        "Amazon_US": "",
        "Amazon_IN": "",
        "Walmart": "",
        "Flipkart": ""
    }
    for aff in affiliates:
        key = f"{aff.store_name}_{aff.country}" if aff.store_name == "Amazon" else aff.store_name
        aff_tags[key] = aff.affiliate_tag
        
    # Get recent usage logs
    logs = db.query(UsageLog).filter(UsageLog.client_id == client.id).order_by(UsageLog.timestamp.desc()).limit(50).all()
    formatted_logs = [
        {
            "id": log.id,
            "endpoint": log.endpoint,
            "country": log.country,
            "credits_deducted": log.credits_deducted,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "response_status": log.response_status
        }
        for log in logs
    ]
    
    return {
        "client_name": client.name,
        "email": client.email,
        "wallet_balance": wallet.balance,
        "currency": wallet.currency,
        "api_key": api_key_str,
        "affiliate_tags": aff_tags,
        "usage_logs": formatted_logs,
        "primary_strategy": client.primary_strategy or "direct",
        "cuelinks_pub_id": client.cuelinks_pub_id or "",
        "amazon_tag": client.amazon_tag or "",
        "flipkart_tag": client.flipkart_tag or "",
        "amazon_tag_in": client.amazon_tag_in or "",
        "amazon_tag_us": client.amazon_tag_us or "",
        "aggregator_network_name": (db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first().aggregator_network_name if db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first() else "CueLinks") or "CueLinks",
        "aggregator_publisher_id": (db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first().aggregator_publisher_id if db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first() else client.cuelinks_pub_id) or "",
        "aggregator_url_template": (db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first().aggregator_url_template if db.query(AffiliateConfig).filter(AffiliateConfig.client_id == client.id).first() else "https://links2re.com/?pub_id={PUB_ID}&url={URL}") or "https://links2re.com/?pub_id={PUB_ID}&url={URL}"
    }

@router.post("/v1/affiliate-config")
def update_affiliate_config(
    payload: AffiliateConfigUpdateRequest,
    client_auth: tuple = Depends(get_dashboard_client),
    db: Session = Depends(get_db)
):
    """Updates client-specific white-label affiliate network configurations."""
    client, _ = client_auth
    client.primary_strategy = payload.primary_strategy
    client.cuelinks_pub_id = payload.cuelinks_pub_id
    client.amazon_tag = payload.amazon_tag
    client.flipkart_tag = payload.flipkart_tag
    client.amazon_tag_in = payload.amazon_tag_in
    client.amazon_tag_us = payload.amazon_tag_us
    
    # Save these columns to client's AffiliateConfig database records for US and IN
    for country in ["US", "IN"]:
        cfg = db.query(AffiliateConfig).filter(
            AffiliateConfig.client_id == client.id,
            AffiliateConfig.country == country,
            AffiliateConfig.store_name == "Amazon"
        ).first()
        if not cfg:
            cfg = AffiliateConfig(
                client_id=client.id,
                country=country,
                store_name="Amazon",
                affiliate_tag="",
                is_active=True
            )
            db.add(cfg)
        
        cfg.amazon_tag_in = payload.amazon_tag_in
        cfg.amazon_tag_us = payload.amazon_tag_us
        cfg.flipkart_subid = payload.flipkart_tag
        
        # Save generic aggregator fields
        cfg.aggregator_network_name = payload.aggregator_network_name or "CueLinks"
        cfg.aggregator_publisher_id = payload.aggregator_publisher_id or payload.cuelinks_pub_id
        cfg.aggregator_url_template = payload.aggregator_url_template or "https://links2re.com/?pub_id={PUB_ID}&url={URL}"
        
    db.commit()
    return {"status": "success", "message": "Monetization configuration successfully updated."}

@router.post("/v1/dashboard/client/affiliate")
def update_client_affiliates(
    payload: AffiliateTagUpdateRequest,
    client_auth: tuple = Depends(get_dashboard_client),
    db: Session = Depends(get_db)
):
    """Updates client-specific affiliate override tags."""
    client, _ = client_auth
    
    # Check if this config override already exists
    existing = db.query(AffiliateConfig).filter(
        AffiliateConfig.client_id == client.id,
        AffiliateConfig.store_name == payload.store_name,
        AffiliateConfig.country == payload.country
    ).first()
    
    if existing:
        existing.affiliate_tag = payload.affiliate_tag
        existing.is_active = True
    else:
        new_cfg = AffiliateConfig(
            client_id=client.id,
            store_name=payload.store_name,
            country=payload.country,
            affiliate_tag=payload.affiliate_tag,
            is_active=True
        )
        db.add(new_cfg)
        
    db.commit()
    return {"status": "success", "message": f"Updated {payload.store_name} ({payload.country}) affiliate tag"}

@router.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the redesigned Single-Page Dashboard SaaS Control Panel built on Tailwind CSS, Lucide Icons, and Chart.js."""
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity SaaS API Gateway Control Panel</title>
    <!-- Tailwind CSS v3 -->
    <script src="https://cdn.tailwindcss.com/3.4.1"></script>
    <!-- Google Fonts: Outfit -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <!-- Lucide Icons CDN -->
    <script src="https://unpkg.com/lucide@latest"></script>
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Outfit', 'sans-serif'],
                    },
                    colors: {
                        slate: {
                            950: '#0b0f19',
                            900: '#161d30',
                            800: '#222b42',
                            700: '#333f5d'
                        },
                        indigo: {
                            500: '#6366f1',
                            600: '#4f46e5',
                            700: '#4338ca'
                        }
                    }
                }
            }
        }
    </script>
    <style>
        body {
            background-color: #0b0f19;
            color: #f8fafc;
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(244, 63, 94, 0.08) 0px, transparent 50%);
            background-attachment: fixed;
        }
        .glass {
            background: rgba(22, 29, 48, 0.65);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .glass-card {
            background: linear-gradient(135deg, rgba(22, 29, 48, 0.7) 0%, rgba(15, 20, 35, 0.8) 100%);
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .glass-card:hover {
            border: 1px solid rgba(99, 102, 241, 0.25);
            box-shadow: 0 12px 35px -10px rgba(99, 102, 241, 0.15);
        }
    </style>
</head>
<body class="min-h-screen flex flex-col font-sans transition-all duration-300">

    <!-- Notification Toast -->
    <div id="toast" class="fixed top-5 right-5 z-[100] transform translate-y-[-100px] opacity-0 transition-all duration-300 glass px-6 py-4 rounded-xl flex items-center gap-3 border border-indigo-500/20 shadow-lg shadow-indigo-500/5">
        <span id="toast-icon" class="text-indigo-400">✨</span>
        <p id="toast-text" class="text-sm font-medium text-slate-200"></p>
    </div>

    <!-- Navigation Header -->
    <header class="w-full glass border-b border-white/5 py-4 px-6 md:px-12 flex items-center justify-between sticky top-0 z-40">
        <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-rose-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                <i data-lucide="shield-check" class="text-white w-6 h-6"></i>
            </div>
            <div>
                <h1 class="text-md font-bold tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">Antigravity Gateway</h1>
                <p class="text-[9px] text-indigo-400 uppercase tracking-widest font-bold">Multi-Tenant SaaS Controller</p>
            </div>
        </div>
        
        <div id="header-user-info" class="hidden flex items-center gap-4">
            <div class="text-right hidden sm:block">
                <p id="header-username" class="text-sm font-semibold text-slate-200"></p>
                <p id="header-role" class="text-[9px] text-slate-400 uppercase tracking-wider font-semibold"></p>
            </div>
            <button onclick="logout()" class="px-4 py-2 text-xs font-semibold text-rose-400 hover:text-white glass rounded-lg border border-rose-500/20 hover:bg-rose-500/10 transition-all flex items-center gap-2">
                <i data-lucide="log-out" class="w-3.5 h-3.5"></i> Sign Out
            </button>
        </div>
    </header>

    <div class="max-w-7xl w-full mx-auto px-4 md:px-8 mt-6">
        <!-- ================= SYSTEM ENGINE STATUS BANNER ================= -->
        <div id="status-banner-container" class="hidden grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <!-- AI Inference -->
            <div class="glass px-4 py-3 rounded-xl flex items-center justify-between border border-white/5">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-400">
                        <i data-lucide="cpu" class="w-4 h-4"></i>
                    </div>
                    <div>
                        <p class="text-[9px] text-slate-400 uppercase font-bold">AI Inference Engine</p>
                        <p class="text-xs font-bold text-slate-200">Connected (AetherAI Enterprise Engine)</p>
                    </div>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="relative flex h-2 w-2">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span class="text-[9px] font-bold text-emerald-400 uppercase">Live</span>
                </div>
            </div>
            
            <!-- Scraper -->
            <div class="glass px-4 py-3 rounded-xl flex items-center justify-between border border-white/5">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-rose-500/10 flex items-center justify-center text-rose-400">
                        <i data-lucide="globe" class="w-4 h-4"></i>
                    </div>
                    <div>
                        <p class="text-[9px] text-slate-400 uppercase font-bold">Scraper Engine</p>
                        <p class="text-xs font-bold text-slate-200">Active (Global Multi-Region Scraper)</p>
                    </div>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="relative flex h-2 w-2">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span class="text-[9px] font-bold text-emerald-400 uppercase">Active</span>
                </div>
            </div>

            <!-- API Status -->
            <div class="glass px-4 py-3 rounded-xl flex items-center justify-between border border-white/5">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400">
                        <i data-lucide="server" class="w-4 h-4"></i>
                    </div>
                    <div>
                        <p class="text-[9px] text-slate-400 uppercase font-bold">API Gateway Status</p>
                        <p class="text-xs font-bold text-slate-200">Healthy (Zero Downtime)</p>
                    </div>
                </div>
                <div class="flex items-center gap-1.5">
                    <span class="relative flex h-2 w-2">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                    </span>
                    <span class="text-[9px] font-bold text-emerald-400 uppercase">Online</span>
                </div>
            </div>
        </div>
    </div>

    <main class="flex-grow flex items-center justify-center p-4 md:p-8">
        
        <!-- ================= LOGIN SCREEN ================= -->
        <div id="login-container" class="w-full max-w-md glass rounded-2xl p-8 border border-white/5 shadow-2xl relative overflow-hidden transition-all duration-300">
            <div class="absolute -top-24 -left-24 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl"></div>
            <div class="absolute -bottom-24 -right-24 w-48 h-48 bg-rose-500/5 rounded-full blur-3xl"></div>
            
            <div class="text-center mb-8 relative z-10">
                <h2 class="text-2xl font-bold bg-gradient-to-r from-white to-slate-300 bg-clip-text text-transparent">Antigravity Gateway</h2>
                <p class="text-slate-400 text-sm mt-2">Connect to client dashboards or manage tenants</p>
            </div>
            
            <!-- Login Tabs -->
            <div class="flex border-b border-white/10 mb-6 relative z-10 text-sm">
                <button onclick="switchLoginTab('key')" id="tab-btn-key" class="w-1/2 py-2 text-center font-medium border-b-2 border-indigo-500 text-indigo-400 transition-all flex items-center justify-center gap-2">
                    <i data-lucide="key" class="w-3.5 h-3.5"></i> X-API-Key
                </button>
                <button onclick="switchLoginTab('email')" id="tab-btn-email" class="w-1/2 py-2 text-center font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition-all flex items-center justify-center gap-2">
                    <i data-lucide="mail" class="w-3.5 h-3.5"></i> Email / Password
                </button>
            </div>
            
            <!-- API Key Login Form -->
            <form id="login-form-key" onsubmit="handleLogin(event, 'key')" class="space-y-4 relative z-10">
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">API key</label>
                    <input type="password" id="input-api-key" placeholder="gw_..." required class="w-full bg-slate-950/80 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all font-mono">
                </div>
                <button type="submit" class="w-full py-3 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-500/10 hover:shadow-indigo-500/20 active:translate-y-[1px] transition-all mt-6 flex items-center justify-center gap-2">
                    <i data-lucide="log-in" class="w-4 h-4"></i> Connect Gateway
                </button>
            </form>
            
            <!-- Email Login Form -->
            <form id="login-form-email" onsubmit="handleLogin(event, 'email')" class="space-y-4 relative z-10 hidden">
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Email Address</label>
                    <input type="email" id="input-email" placeholder="you@company.com" class="w-full bg-slate-950/80 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Password</label>
                    <input type="password" id="input-password" placeholder="••••••••" class="w-full bg-slate-950/80 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all">
                </div>
                <button type="submit" class="w-full py-3 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white rounded-xl text-sm font-semibold shadow-lg shadow-indigo-500/10 hover:shadow-indigo-500/20 active:translate-y-[1px] transition-all mt-6 flex items-center justify-center gap-2">
                    <i data-lucide="log-in" class="w-4 h-4"></i> Sign In
                </button>
            </form>
        </div>

        <!-- ================= CLIENT DASHBOARD ================= -->
        <div id="client-dashboard" class="w-full max-w-7xl hidden grid grid-cols-1 lg:grid-cols-3 gap-8">
            <!-- Left Side Cards -->
            <div class="lg:col-span-1 space-y-8">
                
                <!-- Credit Balance Card -->
                <div class="glass rounded-2xl p-6 relative overflow-hidden transition-all duration-300">
                    <div class="absolute -right-16 -top-16 w-36 h-36 bg-emerald-500/5 rounded-full blur-2xl"></div>
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">Credit Wallet</h3>
                        <div class="w-7 h-7 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400">
                            <i data-lucide="wallet" class="w-4 h-4"></i>
                        </div>
                    </div>
                    
                    <div class="flex items-baseline gap-2 mb-2">
                        <span id="client-wallet-balance" class="text-4xl font-extrabold tracking-tight text-emerald-400">0.00</span>
                        <span class="text-sm font-semibold text-slate-400">/ 100.0 Credits</span>
                    </div>

                    <!-- Progress Bar -->
                    <div class="w-full bg-slate-950/60 rounded-full h-2 mb-4 overflow-hidden border border-white/5">
                        <div id="client-credits-progress" class="bg-gradient-to-r from-emerald-500 to-indigo-500 h-full rounded-full transition-all duration-500" style="width: 0%"></div>
                    </div>
                    
                    <p class="text-[11px] text-slate-400 mb-6 flex justify-between">
                        <span>Deduction: 1.0 per query</span>
                        <span id="client-wallet-percentage">0% remaining</span>
                    </p>
                    
                    <button onclick="requestTopUp()" class="w-full py-3 bg-gradient-to-r from-emerald-500/10 to-emerald-500/20 hover:from-emerald-500/20 hover:to-emerald-500/30 text-emerald-400 rounded-xl text-xs font-semibold border border-emerald-500/20 shadow-lg shadow-emerald-500/5 transition-all flex items-center justify-center gap-2">
                        <i data-lucide="plus-circle" class="w-3.5 h-3.5"></i> Request Top-Up
                    </button>
                </div>

                <!-- Searches Performed and Targets -->
                <div class="grid grid-cols-2 gap-4">
                    <div class="glass rounded-2xl p-4">
                        <p class="text-[10px] text-slate-400 uppercase font-semibold">Queries Run</p>
                        <p class="text-2xl font-bold mt-1 text-white" id="client-stat-queries">0</p>
                    </div>
                    <div class="glass rounded-2xl p-4">
                        <p class="text-[10px] text-slate-400 uppercase font-semibold">Active Targets</p>
                        <p class="text-xs font-semibold mt-2 text-indigo-400 flex items-center gap-1">
                            <span>🇺🇸 USA</span> • <span>🇮🇳 India</span>
                        </p>
                    </div>
                </div>
                
                <!-- API Key Card -->
                <div class="glass rounded-2xl p-6 relative overflow-hidden transition-all duration-300">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest">Active Developer Key</h3>
                        <div class="w-7 h-7 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-400">
                            <i data-lucide="key" class="w-4 h-4"></i>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 mb-6">
                        <div class="flex-grow bg-slate-950/80 border border-white/5 rounded-xl px-4 py-3 text-xs font-mono select-all overflow-x-auto whitespace-nowrap" id="api-key-display">
                            ••••••••••••••••••••••••••••••••
                        </div>
                        <button onclick="toggleKeyVisibility()" class="p-3 glass rounded-xl text-slate-400 hover:text-white" title="Toggle visibility">
                            <i data-lucide="eye" id="toggle-key-eye" class="w-4 h-4"></i>
                        </button>
                    </div>
                    <button onclick="copyApiKey()" class="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-600/15 transition-all flex items-center justify-center gap-2">
                        <i data-lucide="clipboard" class="w-3.5 h-3.5"></i> Copy API Key
                    </button>
                </div>
                
                <!-- Monetization & Affiliate Settings -->
                <div class="glass rounded-2xl p-6 relative overflow-hidden transition-all duration-300">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                            <i data-lucide="link" class="w-4 h-4 text-emerald-400"></i> Monetization & Affiliate Settings
                        </h3>
                    </div>
                    <p class="text-[11px] text-slate-400 mb-4">Configure your primary monetization strategy for target market product clicks.</p>
                    
                    <form onsubmit="saveMonetizationConfig(event)" class="space-y-4 text-xs">
                        <!-- CueLinks aggregator strategy fields -->
                        <div class="space-y-3">
                            <div>
                                <label class="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">CueLinks Publisher ID</label>
                                <input type="text" id="cuelinks-pub-id" placeholder="e.g. 123456" class="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500 text-slate-200">
                                <p class="text-[9px] text-slate-500 mt-1">Fallback aggregator routing for global stores (e.g. Walmart).</p>
                            </div>
                        </div>
                        
                        <!-- Direct store ID overrides strategy fields -->
                        <div class="space-y-3 border-t border-white/5 pt-3">
                            <div>
                                <label class="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Amazon US Store Tag ID</label>
                                <input type="text" id="direct-amazon-tag-us" placeholder="e.g. myshop-20" class="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500 text-slate-200">
                                <p class="text-[9px] text-slate-500 mt-1">Appended directly as '?tag={tag}' query param on Amazon US.</p>
                            </div>
                            <div>
                                <label class="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Amazon IN Store Tag ID</label>
                                <input type="text" id="direct-amazon-tag-in" placeholder="e.g. myshop-21" class="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500 text-slate-200">
                                <p class="text-[9px] text-slate-500 mt-1">Appended directly as '?tag={tag}' query param on Amazon IN.</p>
                            </div>
                            <div>
                                <label class="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Flipkart Affiliate Tag / SubID</label>
                                <input type="text" id="direct-flipkart-tag" placeholder="e.g. mybrand_sub" class="w-full bg-slate-950/60 border border-white/10 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500 text-slate-200">
                                <p class="text-[9px] text-slate-500 mt-1">Appended directly as '?affid={tag}' query param on Flipkart.</p>
                            </div>
                        </div>
                        
                        <button type="submit" class="w-full py-3 bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white rounded-xl text-xs font-semibold shadow-lg shadow-emerald-500/10 transition-all flex items-center justify-center gap-2 border border-emerald-500/20">
                            <i data-lucide="save" class="w-3.5 h-3.5"></i> Save Affiliate Settings
                        </button>
                    </form>
                </div>
            </div>
            
            <!-- Right Side Table (Usage Analytics) -->
            <div class="lg:col-span-2 glass rounded-2xl p-6 overflow-hidden flex flex-col h-[820px]">
                <div class="flex items-center justify-between mb-6">
                    <div>
                        <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                            <i data-lucide="activity" class="w-4 h-4 text-indigo-400"></i> Gateway Routing Logs
                        </h3>
                        <p class="text-xs text-slate-400 mt-1">Real-time developer integration metrics</p>
                    </div>
                    <button onclick="loadClientProfile()" class="px-3 py-2 glass rounded-lg text-xs hover:bg-slate-800 transition-all flex items-center gap-2">
                        <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Refresh
                    </button>
                </div>
                
                <div class="flex-grow overflow-y-auto">
                    <table class="w-full text-left text-xs border-collapse">
                        <thead>
                            <tr class="border-b border-white/5 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                                <th class="py-3 px-2">Timestamp</th>
                                <th class="py-3 px-2">Endpoint</th>
                                <th class="py-3 px-2 text-center">Market</th>
                                <th class="py-3 px-2 text-right">Cost</th>
                                <th class="py-3 px-2 text-center">Status</th>
                            </tr>
                        </thead>
                        <tbody id="client-logs-body" class="divide-y divide-white/5">
                            <!-- Dynamically filled -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ================= ADMIN DASHBOARD ================= -->
        <div id="admin-dashboard" class="w-full max-w-7xl hidden space-y-8">
            
            <!-- Global Metrics Summary -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6">
                <div class="glass rounded-2xl p-6">
                    <p class="text-xs text-slate-400 uppercase tracking-widest font-semibold">Active Clients</p>
                    <p class="text-3xl font-extrabold text-white mt-2" id="admin-stat-clients">0</p>
                </div>
                <div class="glass rounded-2xl p-6">
                    <p class="text-xs text-slate-400 uppercase tracking-widest font-semibold">Processed Calls</p>
                    <p class="text-3xl font-extrabold text-indigo-400 mt-2" id="admin-stat-queries">0</p>
                </div>
                <div class="glass rounded-2xl p-6">
                    <p class="text-xs text-slate-400 uppercase tracking-widest font-semibold">Billed Credits Value</p>
                    <p class="text-3xl font-extrabold text-emerald-400 mt-2" id="admin-stat-credits">0.00 USD</p>
                </div>
                <div class="glass rounded-2xl p-6">
                    <p class="text-xs text-slate-400 uppercase tracking-widest font-semibold">Provider API Costs</p>
                    <p class="text-3xl font-extrabold text-rose-400 mt-2" id="admin-stat-costs">0.00 USD</p>
                </div>
            </div>

            <!-- Revenue & Cost Analytics Graphic Chart -->
            <div class="glass rounded-2xl p-6">
                <div class="mb-4">
                    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                        <i data-lucide="bar-chart-2" class="w-4 h-4 text-emerald-400"></i> Financial Analytics: Billed Value vs Provider API Costs
                    </h3>
                    <p class="text-xs text-slate-400 mt-1">Comparison of Gateway billed revenue (Client credits valued at $0.10/cr) vs combined AI/Scraper third-party costs ($0.015/call)</p>
                </div>
                <div class="h-64 w-full">
                    <canvas id="analytics-chart"></canvas>
                </div>
            </div>

            <!-- Clients Management & Logs Panel -->
            <div class="grid grid-cols-1 xl:grid-cols-3 gap-8">
                
                <!-- Client Registry -->
                <div class="xl:col-span-2 glass rounded-2xl p-6 flex flex-col h-[580px] overflow-hidden">
                    <div class="flex items-center justify-between mb-6">
                        <div>
                            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                                <i data-lucide="users" class="w-4 h-4 text-indigo-400"></i> Tenant Client Registry
                            </h3>
                            <p class="text-xs text-slate-400 mt-1">Configure credit limits and revoke gateway access keys</p>
                        </div>
                        <button onclick="openNewClientModal()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold transition-all flex items-center gap-2 shadow-lg shadow-indigo-600/20">
                            <i data-lucide="plus" class="w-3.5 h-3.5"></i> Onboard Tenant
                        </button>
                    </div>
                    
                    <div class="flex-grow overflow-y-auto">
                        <table class="w-full text-left text-xs border-collapse">
                            <thead>
                                <tr class="border-b border-white/5 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                                    <th class="py-3 px-2">Client Details</th>
                                    <th class="py-3 px-2 text-right">Balance</th>
                                    <th class="py-3 px-2 text-center">Requests</th>
                                    <th class="py-3 px-2">Monthly Status</th>
                                    <th class="py-3 px-2">Key Management</th>
                                    <th class="py-3 px-2 text-center">Actions</th>
                                </tr>
                            </thead>
                            <tbody id="admin-clients-body" class="divide-y divide-white/5">
                                <!-- Filled dynamically -->
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Global Audit Logs -->
                <div class="xl:col-span-1 glass rounded-2xl p-6 flex flex-col h-[580px] overflow-hidden">
                    <div class="flex items-center justify-between mb-6">
                        <div>
                            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
                                <i data-lucide="shield" class="w-4 h-4 text-rose-400"></i> System Transaction Logs
                            </h3>
                            <p class="text-xs text-slate-400 mt-1">Real-time audits across all client tokens</p>
                        </div>
                        <button onclick="loadAdminDashboard()" class="p-2 glass rounded-lg text-xs hover:bg-slate-800 transition-all">
                            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
                        </button>
                    </div>
                    <div class="flex-grow overflow-y-auto">
                        <div class="space-y-4" id="admin-logs-container">
                            <!-- Filled dynamically -->
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <!-- Modal: Add New Client -->
    <div id="new-client-modal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm hidden">
        <div class="glass w-full max-w-md rounded-2xl p-6 border border-white/10 shadow-2xl relative">
            <h3 class="text-lg font-bold text-white mb-4 flex items-center gap-2">
                <i data-lucide="user-plus" class="text-indigo-400 w-5 h-5"></i> Onboard New Tenant
            </h3>
            <form onsubmit="submitNewClient(event)" class="space-y-4 text-sm">
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Company/Client Name</label>
                    <input type="text" id="modal-client-name" required class="w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2.5 text-xs focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Email Address</label>
                    <input type="email" id="modal-client-email" required class="w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2.5 text-xs focus:outline-none focus:border-indigo-500">
                </div>
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Password</label>
                    <input type="password" id="modal-client-password" required class="w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2.5 text-xs focus:outline-none focus:border-indigo-500">
                </div>
                <div class="flex gap-3 mt-6">
                    <button type="button" onclick="closeNewClientModal()" class="w-1/2 py-2.5 glass rounded-xl text-xs font-semibold hover:bg-slate-800 transition-all">
                        Cancel
                    </button>
                    <button type="submit" class="w-1/2 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold shadow-lg shadow-indigo-600/10 transition-all">
                        Onboard Client
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- Modal: Top-up Credits -->
    <div id="topup-modal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm hidden">
        <div class="glass w-full max-w-sm rounded-2xl p-6 border border-white/10 shadow-2xl">
            <h3 class="text-md font-bold text-white mb-2 flex items-center gap-2" id="topup-client-title">
                <i data-lucide="plus-circle" class="text-emerald-400 w-5 h-5"></i> Top-up Credits
            </h3>
            <p class="text-xs text-slate-400 mb-4">Adjust credit balance sheet. Use positive numbers to add, negative numbers to deduct.</p>
            <form onsubmit="submitTopup(event)" class="space-y-4 text-sm">
                <input type="hidden" id="topup-client-id">
                <div>
                    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Credit Value</label>
                    <input type="number" step="0.5" id="topup-amount" required placeholder="e.g. 50.0" class="w-full bg-slate-950 border border-white/10 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-indigo-500">
                </div>
                <div class="flex gap-3 mt-6">
                    <button type="button" onclick="closeTopupModal()" class="w-1/2 py-2.5 glass rounded-xl text-xs font-semibold hover:bg-slate-800 transition-all">
                        Cancel
                    </button>
                    <button type="submit" class="w-1/2 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-lg transition-all">
                        Update Balance
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- Footer -->
    <footer class="w-full py-6 text-center text-[10px] text-slate-500 border-t border-white/5 relative z-10">
        API Gateway SaaS Dashboard. Powered by FastAPI & SQLite. Local Time: <span id="footer-time"></span>
    </footer>

    <script>
        // Set local time in footer
        document.getElementById('footer-time').innerText = new Date().toLocaleString();

        let loginTabMode = 'key';
        let currentApiKey = '';
        let currentUserRole = '';
        let isApiKeyVisible = false;
        let chartInstance = null;

        // Auto check token on start
        window.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            const token = localStorage.getItem('gw_access_token');
            const role = localStorage.getItem('gw_user_role');
            const name = localStorage.getItem('gw_client_name');
            
            if (token && role && name) {
                currentApiKey = token;
                currentUserRole = role;
                showDashboard(role, name);
            }
        });

        // Show Toast helper
        function showToast(text, icon = '✨') {
            const toast = document.getElementById('toast');
            document.getElementById('toast-text').innerText = text;
            document.getElementById('toast-icon').innerText = icon;
            
            toast.className = toast.className.replace('translate-y-[-100px]', 'translate-y-0').replace('opacity-0', 'opacity-100');
            setTimeout(() => {
                toast.className = toast.className.replace('translate-y-0', 'translate-y-[-100px]').replace('opacity-100', 'opacity-0');
            }, 3000);
        }

        // Switch login tabs
        function switchLoginTab(tab) {
            loginTabMode = tab;
            const tabBtnKey = document.getElementById('tab-btn-key');
            const tabBtnEmail = document.getElementById('tab-btn-email');
            const formKey = document.getElementById('login-form-key');
            const formEmail = document.getElementById('login-form-email');
            
            if (tab === 'key') {
                tabBtnKey.className = "w-1/2 py-2 text-center font-medium border-b-2 border-indigo-500 text-indigo-400 transition-all flex items-center justify-center gap-2";
                tabBtnEmail.className = "w-1/2 py-2 text-center font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition-all flex items-center justify-center gap-2";
                formKey.classList.remove('hidden');
                formEmail.classList.add('hidden');
            } else {
                tabBtnEmail.className = "w-1/2 py-2 text-center font-medium border-b-2 border-indigo-500 text-indigo-400 transition-all flex items-center justify-center gap-2";
                tabBtnKey.className = "w-1/2 py-2 text-center font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 transition-all flex items-center justify-center gap-2";
                formEmail.classList.remove('hidden');
                formKey.classList.add('hidden');
            }
        }

        // Sign out
        function logout() {
            localStorage.clear();
            currentApiKey = '';
            currentUserRole = '';
            
            document.getElementById('header-user-info').classList.add('hidden');
            document.getElementById('status-banner-container').classList.add('hidden');
            document.getElementById('client-dashboard').classList.add('hidden');
            document.getElementById('admin-dashboard').classList.add('hidden');
            document.getElementById('login-container').classList.remove('hidden');
            showToast("Successfully logged out", '👋');
        }

        // Toggle Key Visibility
        function toggleKeyVisibility() {
            isApiKeyVisible = !isApiKeyVisible;
            const element = document.getElementById('api-key-display');
            const icon = document.getElementById('toggle-key-eye');
            if (isApiKeyVisible) {
                element.innerText = currentApiKey;
                icon.setAttribute('data-lucide', 'eye-off');
            } else {
                element.innerText = "••••••••••••••••••••••••••••••••";
                icon.setAttribute('data-lucide', 'eye');
            }
            lucide.createIcons();
        }

        function copyApiKey() {
            navigator.clipboard.writeText(currentApiKey).then(() => {
                showToast("API Key copied to clipboard!", '📋');
            });
        }

        // Login Handler
        async function handleLogin(e, type) {
            e.preventDefault();
            
            let payload = {};
            if (type === 'key') {
                const key = document.getElementById('input-api-key').value;
                payload = { api_key: key };
            } else {
                const email = document.getElementById('input-email').value;
                const password = document.getElementById('input-password').value;
                payload = { email: email, password: password };
            }
            
            try {
                const response = await fetch('/v1/dashboard/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Authentication failed");
                }
                
                const data = await response.json();
                
                localStorage.setItem('gw_access_token', data.access_token);
                localStorage.setItem('gw_user_role', data.role);
                localStorage.setItem('gw_client_name', data.client_name);
                
                currentApiKey = data.access_token;
                currentUserRole = data.role;
                
                showDashboard(data.role, data.client_name);
                showToast(`Connected as ${data.client_name}`, '🔑');
                
            } catch (err) {
                showToast(err.message, '⚠️');
            }
        }

        // Show Dashboard View
        function showDashboard(role, name) {
            document.getElementById('login-container').classList.add('hidden');
            document.getElementById('header-user-info').classList.remove('hidden');
            document.getElementById('status-banner-container').classList.remove('hidden');
            document.getElementById('header-username').innerText = name;
            document.getElementById('header-role').innerText = role;
            
            if (role === 'admin') {
                document.getElementById('admin-dashboard').classList.remove('hidden');
                document.getElementById('client-dashboard').classList.add('hidden');
                loadAdminDashboard();
            } else {
                document.getElementById('client-dashboard').classList.remove('hidden');
                document.getElementById('admin-dashboard').classList.add('hidden');
                loadClientProfile();
            }
            lucide.createIcons();
        }

        // Request Top Up (Mock action)
        function requestTopUp() {
            showToast("Top-up request sent to Administrator!", '📩');
        }

        // Save Custom Affiliate Monetization Settings
        async function saveMonetizationConfig(e) {
            e.preventDefault();
            
            const pubId = document.getElementById('cuelinks-pub-id').value;
            const amazonTagUs = document.getElementById('direct-amazon-tag-us').value;
            const amazonTagIn = document.getElementById('direct-amazon-tag-in').value;
            const flipkartTag = document.getElementById('direct-flipkart-tag').value;
            
            try {
                const response = await fetch('/v1/affiliate-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-API-Key': currentApiKey
                    },
                    body: JSON.stringify({
                        primary_strategy: "direct",
                        cuelinks_pub_id: pubId,
                        amazon_tag_us: amazonTagUs,
                        amazon_tag_in: amazonTagIn,
                        flipkart_tag: flipkartTag
                    })
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Failed to update configuration");
                }
                
                showToast("Monetization settings saved!", '🔗');
                loadClientProfile();
            } catch (err) {
                showToast(err.message, '⚠️');
            }
        }

        // Load Client Profile from APIs
        async function loadClientProfile() {
            try {
                const response = await fetch('/v1/dashboard/client/profile', {
                    headers: { 'X-API-Key': currentApiKey }
                });
                
                if (!response.ok) throw new Error("Failed to load profile");
                
                const data = await response.json();
                
                // Credit Balance & percentage progress
                const bal = data.wallet_balance;
                document.getElementById('client-wallet-balance').innerText = bal.toFixed(1);
                
                const pct = Math.min(100, Math.max(0, (bal / 100) * 100));
                document.getElementById('client-credits-progress').style.width = `${pct}%`;
                document.getElementById('client-wallet-percentage').innerText = `${pct.toFixed(0)}% remaining`;
                document.getElementById('client-stat-queries').innerText = data.usage_logs.length;
                
                // Set input values for monetization settings
                document.getElementById('cuelinks-pub-id').value = data.cuelinks_pub_id || '';
                document.getElementById('direct-amazon-tag-us').value = data.amazon_tag_us || '';
                document.getElementById('direct-amazon-tag-in').value = data.amazon_tag_in || '';
                document.getElementById('direct-flipkart-tag').value = data.flipkart_tag || '';
                
                if (isApiKeyVisible) {
                    document.getElementById('api-key-display').innerText = data.api_key;
                }
                
                // Build logs table
                const logsBody = document.getElementById('client-logs-body');
                logsBody.innerHTML = '';
                
                if (data.usage_logs.length === 0) {
                    logsBody.innerHTML = `<tr><td colspan="5" class="py-8 text-center text-slate-500">No routing logs recorded</td></tr>`;
                    return;
                }
                
                data.usage_logs.forEach(log => {
                    const isSuccess = log.response_status === 200;
                    const statusClass = isSuccess ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20';
                    const countryBadge = log.country ? `<span class="px-2 py-0.5 rounded bg-slate-800 text-[10px] font-bold border border-slate-700">${log.country === 'US' ? '🇺🇸 US' : '🇮🇳 IN'}</span>` : '—';
                    
                    const tr = document.createElement('tr');
                    tr.className = "hover:bg-white/[0.02] border-b border-white/5 transition-colors";
                    tr.innerHTML = `
                        <td class="py-3.5 px-2 text-slate-400 font-mono text-[10px]">${log.timestamp}</td>
                        <td class="py-3.5 px-2 font-mono text-indigo-300 font-semibold">${log.endpoint}</td>
                        <td class="py-3.5 px-2 text-center">${countryBadge}</td>
                        <td class="py-3.5 px-2 text-right font-semibold ${log.credits_deducted > 0 ? 'text-emerald-400' : 'text-slate-500'}">-${log.credits_deducted.toFixed(1)}</td>
                        <td class="py-3.5 px-2 text-center">
                            <span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold border ${statusClass}">${log.response_status === 200 ? '200 OK' : log.response_status}</span>
                        </td>
                    `;
                    logsBody.appendChild(tr);
                });
                lucide.createIcons();
            } catch (err) {
                showToast("Failed to sync profile: " + err.message, '⚠️');
            }
        }

        // ================= ADMIN DASHBOARD FUNCTIONS =================
        async function loadAdminDashboard() {
            try {
                const response = await fetch('/admin/metrics', {
                    headers: { 'X-Admin-Token': currentApiKey }
                });
                
                if (!response.ok) throw new Error("Failed to load admin stats");
                
                const data = await response.json();
                
                document.getElementById('admin-stat-clients').innerText = data.total_clients;
                document.getElementById('admin-stat-queries').innerText = data.total_requests;
                document.getElementById('admin-stat-credits').innerText = `${data.total_credits_deducted.toFixed(2)} USD`;
                
                // Calculate provider API costs ($0.015 per query estimate)
                const providerCosts = data.total_requests * 0.015;
                document.getElementById('admin-stat-costs').innerText = `${providerCosts.toFixed(2)} USD`;
                
                // Render Financial Chart comparing Billed credits ($0.10/credit) vs provider costs
                renderAnalyticsChart(data.total_credits_deducted * 0.10, providerCosts);

                // Fill Clients table
                const clientsBody = document.getElementById('admin-clients-body');
                clientsBody.innerHTML = '';
                
                data.clients.forEach(c => {
                    const tr = document.createElement('tr');
                    tr.className = "hover:bg-white/[0.02] border-b border-white/5";
                    
                    const isKeyActive = c.api_key_active;
                    const statusClass = isKeyActive ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border-rose-500/20';
                    const statusLabel = isKeyActive ? 'Active' : 'Revoked';
                    const monthlyStatus = isKeyActive ? '<span class="text-indigo-400 font-semibold">$299/mo</span>' : '<span class="text-slate-500 font-semibold">—</span>';
                    
                    const actionBtn = isKeyActive 
                        ? `<button id="revoke-btn-${c.client_id}" onclick="revokeClientKey(this)" class="px-2.5 py-1 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 rounded border border-rose-500/20 text-[10px] font-bold transition-all">Revoke</button>`
                        : `<button id="activate-btn-${c.client_id}" onclick="activateClientKey(this)" class="px-2.5 py-1 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 rounded border border-emerald-500/20 text-[10px] font-bold transition-all">Activate</button>`;
                    
                    tr.innerHTML = `
                        <td class="py-4 px-2">
                            <p class="font-bold text-slate-200">${c.client_name}</p>
                            <p class="text-[10px] text-slate-400 font-mono mt-0.5">${c.client_id}</p>
                        </td>
                        <td class="py-4 px-2 text-right font-semibold text-emerald-400">${c.current_balance.toFixed(1)} Credits</td>
                        <td class="py-4 px-2 text-center font-semibold text-indigo-400">${c.total_calls}</td>
                        <td class="py-4 px-2 font-semibold">${monthlyStatus}</td>
                        <td class="py-4 px-2">
                            <div class="flex items-center gap-2">
                                <span class="px-2 py-0.5 rounded text-[10px] font-bold border ${statusClass}">${statusLabel}</span>
                                <span class="font-mono text-[9px] text-slate-400 select-all font-semibold">${c.api_key ? c.api_key.substring(0, 10) + '...' : 'None'}</span>
                            </div>
                        </td>
                        <td class="py-4 px-2 text-center">
                            <div class="flex items-center justify-center gap-2">
                                <button onclick="openTopupModal(${c.client_id}, '${c.client_name}')" class="px-2.5 py-1 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 rounded border border-emerald-500/20 text-[10px] font-bold transition-all">Top-Up</button>
                                ${actionBtn}
                            </div>
                        </td>
                    `;
                    clientsBody.appendChild(tr);
                });
                
                // Fill Global Transaction logs list
                const logsContainer = document.getElementById('admin-logs-container');
                logsContainer.innerHTML = '';
                
                if (data.recent_logs.length === 0) {
                    logsContainer.innerHTML = `<p class="text-xs text-slate-500 text-center py-6">No gateway requests executed yet.</p>`;
                    return;
                }
                
                data.recent_logs.forEach(log => {
                    const isSuccess = log.response_status === 200;
                    const statusDot = isSuccess ? 'bg-emerald-400 shadow-lg shadow-emerald-400/50' : 'bg-rose-400 shadow-lg shadow-rose-400/50';
                    const detail = log.country ? `Market: ${log.country}` : 'Root';
                    
                    const div = document.createElement('div');
                    div.className = "flex items-start gap-3 p-3 bg-white/[0.01] hover:bg-white/[0.02] border border-white/5 rounded-xl transition-all";
                    div.innerHTML = `
                        <span class="w-2 h-2 rounded-full ${statusDot} mt-1.5 flex-shrink-0"></span>
                        <div class="flex-grow min-w-0">
                            <div class="flex items-center justify-between gap-2">
                                <span class="font-mono font-semibold text-slate-300 text-xs truncate">${log.endpoint}</span>
                                <span class="text-[10px] text-slate-500 flex-shrink-0 font-mono">${new Date(log.timestamp).toLocaleTimeString()}</span>
                            </div>
                            <div class="flex justify-between items-center mt-1 text-[10px]">
                                <span class="text-slate-400">${detail}</span>
                                <span class="font-bold text-slate-300">-${log.credits_deducted.toFixed(1)} Credits</span>
                            </div>
                        </div>
                    `;
                    logsContainer.appendChild(div);
                });
                lucide.createIcons();
            } catch (err) {
                showToast("Admin dashboard sync failed: " + err.message, '⚠️');
            }
        }

        // Render chart comparison
        function renderAnalyticsChart(billedRevenue, apiCosts) {
            const ctx = document.getElementById('analytics-chart').getContext('2d');
            
            // Destroy previous instance
            if (chartInstance) {
                chartInstance.destroy();
            }
            
            chartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Gateway Billed Revenue ($)', 'Scraper & LLM API Provider Cost ($)', 'Net System Margin ($)'],
                    datasets: [{
                        label: 'Financial Flow',
                        data: [billedRevenue, apiCosts, (billedRevenue - apiCosts)],
                        backgroundColor: [
                            'rgba(16, 185, 129, 0.25)', // Emerald
                            'rgba(244, 63, 94, 0.25)',   // Rose
                            'rgba(99, 102, 241, 0.25)'   // Indigo
                        ],
                        borderColor: [
                            'rgb(16, 185, 129)',
                            'rgb(244, 63, 94)',
                            'rgb(99, 102, 241)'
                        ],
                        borderWidth: 2,
                        borderRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#94a3b8' }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: '#94a3b8' }
                        }
                    }
                }
            });
        }

        // Modal triggers
        function openNewClientModal() {
            document.getElementById('new-client-modal').classList.remove('hidden');
        }
        function closeNewClientModal() {
            document.getElementById('new-client-modal').classList.add('hidden');
        }
        function openTopupModal(clientId, clientName) {
            document.getElementById('topup-client-id').value = clientId;
            document.getElementById('topup-client-title').innerText = `Top-up Credits: ${clientName}`;
            document.getElementById('topup-modal').classList.remove('hidden');
        }
        function closeTopupModal() {
            document.getElementById('topup-modal').classList.add('hidden');
        }

        // Onboard Client Submit
        async function submitNewClient(e) {
            e.preventDefault();
            
            const name = document.getElementById('modal-client-name').value;
            const email = document.getElementById('modal-client-email').value;
            const password = document.getElementById('modal-client-password').value;
            
            try {
                const response = await fetch('/admin/clients', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Token': currentApiKey
                    },
                    body: JSON.stringify({
                        name: name,
                        email: email,
                        password: password
                    })
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || "Onboarding failed");
                }
                
                const clientResponse = await response.json();
                closeNewClientModal();
                showToast(`Client ${name} onboarded successfully!`, '🚀');
                
                alert(`Client registered successfully!\\n\\nAPI KEY: ${clientResponse.api_keys[0].key}\\nEmail: ${email}\\nPassword: ${password}\\n\\nPlease copy the key, it won't be shown again.`);
                loadAdminDashboard();
                
            } catch (err) {
                showToast(err.message, '⚠️');
            }
        }

        // Topup Submit
        async function submitTopup(e) {
            e.preventDefault();
            
            const clientId = parseInt(document.getElementById('topup-client-id').value);
            const amount = parseFloat(document.getElementById('topup-amount').value);
            
            try {
                const response = await fetch('/admin/credits/topup', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Token': currentApiKey
                    },
                    body: JSON.stringify({
                        client_id: clientId,
                        amount: amount
                    })
                });
                
                if (!response.ok) throw new Error("Top-up request failed");
                
                closeTopupModal();
                showToast("Wallet balance updated!", '💰');
                loadAdminDashboard();
                
            } catch (err) {
                showToast(err.message, '⚠️');
            }
        }

        // Revoke Client Key
        async function revokeClientKey(btn) {
            if (!confirm("Are you sure you want to revoke this client's active API key?\\nThis acts as a gateway kill-switch.")) return;
            
            try {
                const response = await fetch('/admin/metrics', {
                    headers: { 'X-Admin-Token': currentApiKey }
                });
                const metrics = await response.json();
                
                const clientId = parseInt(btn.id.replace('revoke-btn-', ''));
                const matchedClient = metrics.clients.find(c => c.client_id === clientId);
                
                if (!matchedClient || !matchedClient.api_key) {
                    showToast("No active key found to revoke", '⚠️');
                    return;
                }
                
                const revokeResp = await fetch('/admin/keys/revoke', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Token': currentApiKey
                    },
                    body: JSON.stringify({ key: matchedClient.api_key })
                });
                
                if (!revokeResp.ok) throw new Error("Revocation failed");
                
                showToast("Client API Key Revoked!", '🛑');
                loadAdminDashboard();
                
            } catch (e) {
                showToast(e.message, '⚠️');
            }
        }

        // Activate Client Key
        async function activateClientKey(btn) {
            if (!confirm("Are you sure you want to re-activate this client's revoked API key?")) return;
            
            try {
                const response = await fetch('/admin/metrics', {
                    headers: { 'X-Admin-Token': currentApiKey }
                });
                const metrics = await response.json();
                
                const clientId = parseInt(btn.id.replace('activate-btn-', ''));
                const matchedClient = metrics.clients.find(c => c.client_id === clientId);
                
                if (!matchedClient || !matchedClient.api_key) {
                    showToast("No key found to activate", '⚠️');
                    return;
                }
                
                const activateResp = await fetch('/admin/keys/activate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Token': currentApiKey
                    },
                    body: JSON.stringify({ key: matchedClient.api_key })
                });
                
                if (!activateResp.ok) throw new Error("Activation failed");
                
                showToast("Client API Key Activated!", '🟢');
                loadAdminDashboard();
                
            } catch (e) {
                showToast(e.message, '⚠️');
            }
        }
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content, status_code=200)
