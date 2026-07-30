import sys
import os
import json
from fastapi.testclient import TestClient

# Ensure current directory is in Python path so we can import the project modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app

client = TestClient(app)

ADMIN_TOKEN = "gateway_admin_secret_token_123"

def run_tests():
    print("=" * 60)
    print("STARTING END-TO-END GATEWAY INTEGRATION TESTS")
    print("=" * 60)

    # Use TestClient with context manager to trigger lifespan events (database creation & seeding)
    with TestClient(app) as client:
        # Delete all logs, api keys, wallets, and clients (except Acme Dev) to ensure a clean test run
        from database import SessionLocal
        from models.client import Client
        from models.usage_log import UsageLog
        from models.api_key import ApiKey
        from models.wallet import CreditWallet
        from models.affiliate import AffiliateConfig
        db = SessionLocal()
        try:
            db.query(UsageLog).delete()
            db.query(ApiKey).delete()
            db.query(CreditWallet).delete()
            db.query(AffiliateConfig).delete()
            db.query(Client).delete()
            db.commit()
            
            # Re-seed the default Acme Dev client and default configs
            from database import seed_database
            seed_database(db)
        except Exception as e:
            print(f"Error resetting test DB: {e}")
            db.rollback()
        finally:
            db.close()

        # 1. Health check
        print("\n[STEP 1] Testing Gateway Health Check")
        resp = client.get("/")
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.json()}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "online"

        # 2. Register Client
        print("\n[STEP 2] Admin: Creating Client 'Acme AI Assistant'")
        headers = {"X-Admin-Token": ADMIN_TOKEN}
        payload = {
            "name": "Acme AI Assistant",
            "email": "assistant@acme.com",
            "password": "assistantpassword"
        }
        resp = client.post("/admin/clients", headers=headers, json=payload)
        print(f"Status Code: {resp.status_code}")
        client_data = resp.json()
        print(f"Response: {json.dumps(client_data, indent=2)}")
        
        assert resp.status_code == 201
        client_id = client_data["id"]
        api_key = client_data["api_keys"][0]["key"]
        wallet_balance = client_data["wallet"]["balance"]
        print(f"Client Registered: ID={client_id}, Initial API Key={api_key}, Balance={wallet_balance}")
        
        assert wallet_balance == 100.0
        assert api_key.startswith("gw_")

        # 3. Test US Search Request
        print("\n[STEP 3] Client: Performing Search Request (US Market)")
        client_headers = {"X-API-Key": api_key}
        search_payload_us = {
            "query": "gaming laptop under 1200",
            "country": "US"
        }
        resp = client.post("/v1/search", headers=client_headers, json=search_payload_us)
        print(f"Status Code: {resp.status_code}")
        search_data_us = resp.json()
        
        assert resp.status_code == 200
        assert len(search_data_us["results"]) == 3
        assert search_data_us["credits_remaining"] == 99.0
        for pick in search_data_us["results"]:
            assert pick["affiliate_url"] == pick["original_url"], "URLs were not clean plain product links!"
        
        # 4. Test IN Search Request
        print("\n[STEP 4] Client: Performing Search Request (IN Market)")
        search_payload_in = {
            "query": "flagship phone under 50000",
            "country": "IN"
        }
        resp = client.post("/v1/search", headers=client_headers, json=search_payload_in)
        print(f"Status Code: {resp.status_code}")
        search_data_in = resp.json()
        
        assert resp.status_code == 200
        assert len(search_data_in["results"]) == 3
        assert search_data_in["credits_remaining"] == 98.0
        for pick in search_data_in["results"]:
            assert pick["affiliate_url"] == pick["original_url"], "URLs were not clean plain product links!"

        # 5. Draining Wallet to 0.0
        print("\n[STEP 5] Admin: Draining wallet balance to 0.0")
        topup_payload = {
            "client_id": client_id,
            "amount": -98.0 # 98.0 - 98.0 = 0.0
        }
        resp = client.post("/admin/credits/topup", headers=headers, json=topup_payload)
        print(f"Status Code: {resp.status_code}")
        topup_data = resp.json()
        assert resp.status_code == 200
        assert topup_data["new_balance"] == 0.0

        # 6. Test 402 Payment Required Block
        print("\n[STEP 6] Client: Testing 402 Payment Required on Zero Balance")
        resp = client.post("/v1/search", headers=client_headers, json=search_payload_us)
        print(f"Status Code: {resp.status_code}")
        assert resp.status_code == 402

        # 7. Revoking API Key
        print("\n[STEP 7] Admin: Revoking Client API Key (Kill Switch)")
        revoke_payload = {"key": api_key}
        resp = client.post("/admin/keys/revoke", headers=headers, json=revoke_payload)
        print(f"Status Code: {resp.status_code}")
        assert resp.status_code == 200
        
        # 8. Test 401 Unauthorized Block
        print("\n[STEP 8] Client: Testing 401 Unauthorized with Revoked Key")
        resp = client.post("/v1/search", headers=client_headers, json=search_payload_us)
        print(f"Status Code: {resp.status_code}")
        assert resp.status_code == 401

        # 9. Top-up Wallet and Generate New Key
        print("\n[STEP 9] Admin: Adding Credits & Generating a New Key")
        topup_payload_2 = {
            "client_id": client_id,
            "amount": 5.0
        }
        client.post("/admin/credits/topup", headers=headers, json=topup_payload_2)
        gen_key_payload = {"client_id": client_id}
        resp = client.post("/admin/keys/generate", headers=headers, json=gen_key_payload)
        new_key = resp.json()["key"]
        print(f"Generated New API Key: {new_key}")
        
        client_headers_2 = {"X-API-Key": new_key}
        resp = client.post("/v1/search", headers=client_headers_2, json=search_payload_us)
        print(f"New Key Search Status: {resp.status_code}")
        assert resp.status_code == 200
        assert resp.json()["credits_remaining"] == 4.0

        # 10. Audit Metrics
        print("\n[STEP 10] Admin: Auditing Gateway Metrics")
        resp = client.get("/admin/metrics", headers=headers)
        print(f"Status Code: {resp.status_code}")
        metrics = resp.json()
        assert resp.status_code == 200
        # Account for seeded client (Acme Dev) + newly registered client (Acme AI Assistant)
        assert metrics["total_clients"] == 2 
        # Total requests: step 3 + step 4 + step 9 = 3 requests
        assert metrics["total_requests"] == 3

        # 11. Test Dashboard Page GET
        print("\n[STEP 11] Dashboard: Testing GET /dashboard")
        resp = client.get("/dashboard")
        print(f"Status Code: {resp.status_code}")
        assert resp.status_code == 200
        assert "<title>Antigravity SaaS API Gateway Control Panel</title>" in resp.text

        # 12. Test Dashboard Login (Admin)
        print("\n[STEP 12] Dashboard: Testing Admin Login via credentials")
        login_payload = {
            "email": "admin@gateway.local",
            "password": ADMIN_TOKEN
        }
        resp = client.post("/v1/dashboard/login", json=login_payload)
        print(f"Status Code: {resp.status_code}")
        login_data = resp.json()
        print(f"Response: {login_data}")
        assert resp.status_code == 200
        assert login_data["role"] == "admin"
        assert login_data["access_token"] == ADMIN_TOKEN

        # 13. Test Dashboard Login (Seeded Client)
        print("\n[STEP 13] Dashboard: Testing Client Login (Seeded Acme Dev)")
        login_payload_client = {
            "email": "acme@gateway.local",
            "password": "password123"
        }
        resp = client.post("/v1/dashboard/login", json=login_payload_client)
        print(f"Status Code: {resp.status_code}")
        login_data_client = resp.json()
        print(f"Response: {login_data_client}")
        assert resp.status_code == 200
        assert login_data_client["role"] == "client"
        assert login_data_client["client_name"] == "Acme Dev"
        assert login_data_client["access_token"] == "gw_acmedemosecretkey123"

        # 14. Test Client Profile Fetch & Custom Affiliate Tags
        print("\n[STEP 14] Dashboard: Fetching Client Profile & Updating Affiliate Config")
        client_key = "gw_acmedemosecretkey123"
        profile_headers = {"X-API-Key": client_key}
        resp = client.get("/v1/dashboard/client/profile", headers=profile_headers)
        print(f"Profile Status Code: {resp.status_code}")
        profile_data = resp.json()
        assert resp.status_code == 200
        assert profile_data["client_name"] == "Acme Dev"
        assert profile_data["wallet_balance"] == 100.0
        
        # Save custom tag for Amazon US
        aff_payload = {
            "store_name": "Amazon",
            "country": "US",
            "affiliate_tag": "acme-custom-us-amazon"
        }
        resp = client.post("/v1/dashboard/client/affiliate", headers=profile_headers, json=aff_payload)
        assert resp.status_code == 200
        
        # Verify tag is updated in profile
        resp = client.get("/v1/dashboard/client/profile", headers=profile_headers)
        assert resp.json()["affiliate_tags"]["Amazon_US"] == "acme-custom-us-amazon"
        print("Custom Amazon US Tag saved successfully!")

        # 15. Verify Affiliate Override is applied in search query
        print("\n[STEP 15] Gateway: Verifying Affiliate Overrides on Search Endpoint")
        search_payload_override = {
            "query": "ultraboot shoes",
            "country": "US"
        }
        resp = client.post("/v1/search", headers=profile_headers, json=search_payload_override)
        print(f"Status Code: {resp.status_code}")
        search_res = resp.json()
        
        amazon_url_has_custom_tag = False
        walmart_url_has_default_tag = False
        
        for pick in search_res["results"]:
            print(f" - {pick['source']} | Affiliate URL: {pick['affiliate_url']}")
            if pick["source"] == "Amazon":
                if "tag=acme-custom-us-amazon" in pick["affiliate_url"]:
                    amazon_url_has_custom_tag = True
            elif pick["source"] == "Walmart":
                if "affid=us-walmart-partner-20" in pick["affiliate_url"]:
                    walmart_url_has_default_tag = True
                    
        assert amazon_url_has_custom_tag, "Amazon URL did not use client's custom override affiliate tag!"
        assert walmart_url_has_default_tag, "Walmart URL did not fallback to system default affiliate tag!"
        print("Affiliate override verified: Amazon URL used customized tag, Walmart URL fell back to default tag.")
        # 16. Test CueLinks Monetization Strategy
        print("\n[STEP 16] Dashboard: Testing CueLinks Network Strategy")
        cuelinks_payload = {
            "primary_strategy": "cuelinks",
            "cuelinks_pub_id": "999999",
            "amazon_tag_in": "",
            "amazon_tag_us": "",
            "flipkart_tag": ""
        }
        resp = client.post("/v1/affiliate-config", headers=profile_headers, json=cuelinks_payload)
        assert resp.status_code == 200
        
        # Verify in profile
        resp = client.get("/v1/dashboard/client/profile", headers=profile_headers)
        profile_json = resp.json()
        assert profile_json["primary_strategy"] == "cuelinks"
        assert profile_json["cuelinks_pub_id"] == "999999"
        
        # Verify search query formats URLs as CueLinks redirects using links2re.com
        resp = client.post("/v1/search", headers=profile_headers, json=search_payload_override)
        assert resp.status_code == 200
        search_res = resp.json()
        
        all_urls_are_cuelinks = True
        for pick in search_res["results"]:
            print(f" - {pick['source']} | CueLinks URL: {pick['affiliate_url']}")
            if not pick["affiliate_url"].startswith("https://links2re.com/?pub_id=999999"):
                all_urls_are_cuelinks = False
                
        assert all_urls_are_cuelinks, "Some product URLs were not wrapped with links2re.com redirects!"
        print("CueLinks redirect generation verified successfully!")

        # 17. Test Direct & CueLinks Fallback Strategy (Simultaneous configuration)
        print("\n[STEP 17] Dashboard: Testing Direct Store Tags with CueLinks Fallback Strategy")
        direct_payload = {
            "primary_strategy": "direct",
            "cuelinks_pub_id": "999999", # Simultaneously set CueLinks ID
            "amazon_tag_in": "direct-amzn-tag-in",
            "amazon_tag_us": "direct-amzn-tag-us",
            "flipkart_tag": "direct-fk-tag"
        }
        resp = client.post("/v1/affiliate-config", headers=profile_headers, json=direct_payload)
        assert resp.status_code == 200
        
        # Verify in profile
        resp = client.get("/v1/dashboard/client/profile", headers=profile_headers)
        profile_json = resp.json()
        assert profile_json["cuelinks_pub_id"] == "999999"
        assert profile_json["amazon_tag_in"] == "direct-amzn-tag-in"
        assert profile_json["amazon_tag_us"] == "direct-amzn-tag-us"
        assert profile_json["flipkart_tag"] == "direct-fk-tag"
        
        # Verify search query applies direct store tags in IN
        search_payload_in_override = {
            "query": "superfast charger",
            "country": "IN"
        }
        resp = client.post("/v1/search", headers=profile_headers, json=search_payload_in_override)
        assert resp.status_code == 200
        search_res = resp.json()
        
        amazon_uses_direct_tag = False
        flipkart_uses_direct_tag = False
        
        for pick in search_res["results"]:
            print(f" - {pick['source']} | Direct/IN URL: {pick['affiliate_url']}")
            if pick["source"] == "Amazon" and "tag=direct-amzn-tag-in" in pick["affiliate_url"]:
                amazon_uses_direct_tag = True
            elif pick["source"] == "Flipkart" and "affid=direct-fk-tag" in pick["affiliate_url"]:
                flipkart_uses_direct_tag = True
                
        assert amazon_uses_direct_tag, "Amazon IN URL did not use direct-amzn-tag-in override!"
        assert flipkart_uses_direct_tag, "Flipkart URL did not use direct-fk-tag override!"
        
        # Verify search query applies direct store tags in US AND falls back to CueLinks for Walmart
        resp = client.post("/v1/search", headers=profile_headers, json=search_payload_override)
        assert resp.status_code == 200
        search_res_us = resp.json()
        
        amazon_us_uses_direct_tag = False
        walmart_falls_back_to_cuelinks = False
        
        for pick in search_res_us["results"]:
            print(f" - {pick['source']} | Hybrid/US URL: {pick['affiliate_url']}")
            if pick["source"] == "Amazon" and "tag=direct-amzn-tag-us" in pick["affiliate_url"]:
                amazon_us_uses_direct_tag = True
            elif pick["source"] == "Walmart" and pick["affiliate_url"].startswith("https://links2re.com/?pub_id=999999"):
                walmart_falls_back_to_cuelinks = True
                
        assert amazon_us_uses_direct_tag, "Amazon US URL did not use direct-amzn-tag-us override!"
        assert walmart_falls_back_to_cuelinks, "Walmart URL did not fallback to CueLinks redirect!"
        print("Smart Hybrid affiliate link generation verified successfully!")

        # 18. Test Coupon Waterfall & Coupon Reveal Endpoint
        print("\n[STEP 18] Gateway: Testing Coupon Waterfall & Coupon Reveal Endpoint")
        resp = client.post("/v1/search", headers=profile_headers, json=search_payload_override)
        assert resp.status_code == 200
        search_res_waterfall = resp.json()
        
        has_coupon_waterfall_fields = False
        sample_reveal_url = None
        
        for pick in search_res_waterfall["results"]:
            print(f" - {pick['title']} | Coupon Code: {pick['coupon_code']} | Status: {pick['coupon_status']}")
            assert "coupon_code" in pick
            assert "coupon_description" in pick
            assert "coupon_status" in pick
            assert "reveal_url" in pick
            
            if pick["coupon_status"] == "Auto Coupon":
                has_coupon_waterfall_fields = True
                if not sample_reveal_url:
                    sample_reveal_url = pick["reveal_url"]
                    
        assert has_coupon_waterfall_fields, "Coupon waterfall did not auto-detect store coupons!"
        print("Coupon waterfall auto-detection verified successfully!")
        
        # Verify POST /v1/reveal-coupon endpoint response
        assert sample_reveal_url is not None
        # Extract relative path from URL
        relative_reveal_url = sample_reveal_url
        if relative_reveal_url.startswith("http"):
            from urllib.parse import urlparse
            parsed = urlparse(relative_reveal_url)
            relative_reveal_url = parsed.path + "?" + parsed.query
            
        resp = client.post(relative_reveal_url)
        assert resp.status_code == 200
        json_resp = resp.json()
        assert json_resp["status"] == "success"
        assert json_resp["coupon_code"] == "SHOES15"
        print("Coupon reveal POST /v1/reveal-coupon verified successfully!")

    print("\n" + "=" * 60)
    print("ALL GATEWAY MIDDLEWARE & DASHBOARD INTEGRATION TESTS PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    # Clean up the SQLite DB before starting the test to ensure clean runs
    if os.path.exists("gateway.db"):
        try:
            os.remove("gateway.db")
        except OSError:
            pass
            
    run_tests()
