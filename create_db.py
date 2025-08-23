# create_db.py
import pandas as pd
import sqlite3
import json
import os

JSON_FILE = 'instrument_list.json'
DB_FILE = 'instruments.db'

def create_database():
    """
    Reads the large JSON instrument file and converts it into an
    indexed SQLite database for fast, memory-efficient lookups.
    """
    if not os.path.exists(JSON_FILE):
        print(f"Error: '{JSON_FILE}' not found. Please run the download_instruments.py script first.")
        return

    print(f"Loading '{JSON_FILE}' into memory for processing...")
    try:
        df = pd.read_json(JSON_FILE)
    except Exception as e:
        print(f"Error reading JSON file: {e}")
        print("The file might be corrupted or in an unexpected format.")
        return
        
    print("File loaded. Converting data types...")

    # Ensure token is a string
    df['token'] = df['token'].astype(str)
    
    # Select and rename columns for clarity in the database
    df = df[['symbol', 'token', 'exch_seg', 'name']]
    df = df.rename(columns={'symbol': 'tradingsymbol', 'token': 'symboltoken', 'exch_seg': 'exchange'})

    print(f"Connecting to SQLite database '{DB_FILE}'...")
    conn = sqlite3.connect(DB_FILE)
    
    print(f"Writing {len(df)} records to the 'instruments' table...")
    # Write the dataframe to a SQL table
    df.to_sql('instruments', conn, if_exists='replace', index=False)
    
    print("Creating an index on 'tradingsymbol' for fast lookups...")
    # An index makes searching by tradingsymbol extremely fast
    conn.execute('CREATE INDEX idx_tradingsymbol ON instruments (tradingsymbol)')
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Success! Database '{DB_FILE}' has been created.")
    print("You can now run the agent.")

if __name__ == '__main__':
    create_database()