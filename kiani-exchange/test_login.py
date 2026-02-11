#!/usr/bin/env python3
import requests
import json

BASE_URL = "https://miniapp.peerexo.com/api"

def test_login():
    """Test login functionality"""
    print("Testing login endpoint...")
    
    # Test with a known test user
    test_data = {
        "phone_number": "09123456789",
        "password": "Test1234"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/users/login",
            json=test_data,
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print("✓ Login successful!")
            print(f"Token: {data.get('token', 'No token')[:20]}...")
            return data.get('token')
        else:
            print("✗ Login failed")
            
    except Exception as e:
        print(f"✗ Error: {e}")
    
    return None

def test_rates():
    """Test rates endpoint"""
    print("\nTesting rates endpoint...")
    
    try:
        response = requests.get(
            f"{BASE_URL}/rates/current",
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            print("✓ Rates endpoint working!")
        else:
            print("✗ Rates endpoint failed")
            
    except Exception as e:
        print(f"✗ Error: {e}")

def test_user_profile(token):
    """Test user profile endpoint"""
    if not token:
        return
    
    print("\nTesting user profile endpoint...")
    
    try:
        response = requests.get(
            f"{BASE_URL}/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            print("✓ User profile working!")
        else:
            print("✗ User profile failed")
            
    except Exception as e:
        print(f"✗ Error: {e}")

def test_ehraz():
    """Test EHRAZ verification"""
    print("\nTesting EHRAZ verification...")
    
    test_data = {
        "cardNumber": "6037991234567890",
        "nationalCode": "1234567890",
        "birthDate": "13701212"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/verify/ehraz",
            json=test_data,
            timeout=10
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            print("✓ EHRAZ verification working!")
        else:
            print("✗ EHRAZ verification failed")
            
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    print("=== Testing Kiani Exchange API ===\n")
    
    # Test rates first
    test_rates()
    
    # Test login
    token = test_login()
    
    # Test user profile if login successful
    if token:
        test_user_profile(token)
    
    # Test EHRAZ verification
    test_ehraz()
    
    print("\n=== Testing Complete ===")