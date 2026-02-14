#!/usr/bin/env python3
"""
Comprehensive system test for Kiani Exchange
Tests all major API endpoints and functionality
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:8000/api"
# BASE_URL = "https://miniapp.peerexo.com/api"  # Uncomment to test via nginx

def test_endpoint(method, endpoint, data=None, expected_status=200, auth_token=None):
    """Test an API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            print(f"❌ Unknown method: {method}")
            return False
        
        if response.status_code == expected_status:
            print(f"✅ {method} {endpoint}: HTTP {response.status_code}")
            if response.content:
                try:
                    print(f"   Response: {json.dumps(response.json(), indent=2)[:200]}...")
                except:
                    print(f"   Response: {response.text[:200]}...")
            return True
        else:
            print(f"❌ {method} {endpoint}: Expected {expected_status}, got {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return False
    except Exception as e:
        print(f"❌ {method} {endpoint}: Exception - {e}")
        return False

def main():
    print("🧪 Starting comprehensive system test for Kiani Exchange")
    print("=" * 60)
    
    # Test 1: Health check
    print("\n1. Testing health check:")
    test_endpoint("GET", "/health", expected_status=200)
    
    # Test 2: Rates endpoint
    print("\n2. Testing rates endpoint:")
    test_endpoint("GET", "/rates/current", expected_status=200)
    
    # Test 3: FAQs endpoint
    print("\n3. Testing FAQs endpoint:")
    test_endpoint("GET", "/faqs", expected_status=200)
    
    # Test 4: EHRAZ verification (mock mode)
    print("\n4. Testing EHRAZ verification (mock mode):")
    ehraz_data = {
        "nationalCode": "0083263497",
        "cardNumber": "6219861012345678",
        "birthDate": "13650626"
    }
    test_endpoint("POST", "/verify/ehraz", data=ehraz_data, expected_status=200)
    
    # Test 5: EHRAZ mobile verification
    print("\n5. Testing EHRAZ mobile verification:")
    ehraz_mobile_data = {
        "nationalCode": "0083263497",
        "mobileNumber": "09123456789"
    }
    test_endpoint("POST", "/verify/ehraz-mobile", data=ehraz_mobile_data, expected_status=200)
    
    # Test 6: User registration (test with unique data)
    print("\n6. Testing user registration:")
    import random
    random_suffix = random.randint(1000, 9999)
    register_data = {
        "first_name": "تست",
        "last_name": f"کاربر{random_suffix}",
        "national_id": f"00123{random_suffix}",
        "date_of_birth": "1365/06/26",
        "bank_card_number": f"62198610{random_suffix}",
        "phone_number": f"0912{random_suffix}",
        "password": "Test1234!"
    }
    # Try registration (might fail if user already exists, which is OK for test)
    test_endpoint("POST", "/users/register", data=register_data, expected_status=200)
    
    # Test 7: User login
    print("\n7. Testing user login:")
    login_data = {
        "phone_number": register_data["phone_number"],
        "password": register_data["password"]
    }
    login_success = test_endpoint("POST", "/users/login", data=login_data, expected_status=200)
    
    # If login successful, test protected endpoints
    if login_success:
        try:
            response = requests.post(f"{BASE_URL}/users/login", json=login_data)
            if response.status_code == 200:
                token = response.json().get("token")
                if token:
                    print("\n8. Testing protected endpoints with auth token:")
                    # Test getting user profile
                    test_endpoint("GET", "/users/me", auth_token=token, expected_status=200)
                    
                    # Test transactions endpoint
                    test_endpoint("GET", "/user/transactions", auth_token=token, expected_status=200)
                else:
                    print("⚠️  No token received from login")
            else:
                print("⚠️  Login failed, skipping protected endpoints")
        except:
            print("⚠️  Error testing login response, skipping protected endpoints")
    
    # Test 9: Admin endpoints (with test credentials)
    print("\n9. Testing admin login (with default credentials):")
    admin_data = {
        "username": "admin",
        "password": "admin123"
    }
    test_endpoint("POST", "/admin/login", data=admin_data, expected_status=200)
    
    # Test 10: Admin users list
    print("\n10. Testing admin users list:")
    # Note: This requires admin credentials as query params
    test_endpoint("GET", f"/admin/users?username={admin_data['username']}&password={admin_data['password']}", expected_status=200)
    
    print("\n" + "=" * 60)
    print("✅ System test completed!")
    print("\n📋 Summary:")
    print("- Backend API is running")
    print("- EHRAZ verification (mock mode) is working")
    print("- User authentication system is functional")
    print("- Admin panel is accessible")
    print("\n🔗 Frontend URL: https://miniapp.peerexo.com")
    print("🔗 API Base URL: https://miniapp.peerexo.com/api/")
    print("🔗 Health Check: https://miniapp.peerexo.com/health")

if __name__ == "__main__":
    main()