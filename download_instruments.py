# download_instruments.py
import requests
import json

# This is the direct URL to Angel One's instrument list file
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
FILENAME = "instrument_list.json"

def download_file():
    """
    Downloads the latest instrument master file directly from the Angel One server.
    """
    print(f"Attempting to download the latest instrument list from Angel One...")
    print(f"URL: {URL}")

    try:
        # Make the HTTP GET request to download the file
        response = requests.get(URL, timeout=30)
        # Raise an exception if the request was unsuccessful (e.g., 404 Not Found)
        response.raise_for_status()

        # Parse the JSON data from the response
        data = response.json()

        # Save the data to our local file
        with open(FILENAME, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\n✅ Success! Instrument list with {len(data)} records downloaded and saved as '{FILENAME}'.")
        print("You can now proceed to the next step.")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error: Failed to download the file. Please check your internet connection and the URL.")
        print(f"Details: {e}")
    except json.JSONDecodeError:
        print(f"\n❌ Error: The downloaded file is not valid JSON. Angel One might have changed the format or the URL.")

if __name__ == '__main__':
    download_file()