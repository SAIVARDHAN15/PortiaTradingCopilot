import pyotp
import os
from SmartApi import SmartConnect  # Angel One SmartAPI Python SDK

# === Replace with your actual details ===
CLIENT_CODE = "V52275032"
PASSWORD = "1977"
TOTP_SECRET = "6VZKEOMOBYCMF246LIG5YH3TMQ"   # Base32 string from SmartAPI portal
API_KEY = "Hm82igeg"

def main():
    try:
        # Generate current TOTP
        totp = pyotp.TOTP(TOTP_SECRET).now()
        print(f"Generated TOTP: {totp}")

        # Create SmartConnect client
        obj = SmartConnect(api_key=API_KEY)

        # Perform login
        data = obj.generateSession(CLIENT_CODE, PASSWORD, totp)
        print("✅ Login successful")
        print("Session data:", data)

    except Exception as e:
        print("❌ Login failed:", str(e))

if __name__ == "__main__":
    main()
