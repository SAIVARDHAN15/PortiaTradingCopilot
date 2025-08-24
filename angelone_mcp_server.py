# angelone_mcp_server.py
import os
import sys
import json
import time
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from SmartApi import SmartConnect
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

print(f"[MCP START] PID={os.getpid()} ARGS={sys.argv}", flush=True)

SESSION_FILE = "angel_session.json"

def _save_session(data: dict):
    """Saves session data to a JSON file."""
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)

def _load_session() -> Optional[dict]:
    """Loads session data from a JSON file if it exists."""
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            return json.load(f)
    return None

mcp = FastMCP("angelone-mcp")

# --- Pydantic Models for typed inputs ---
class OhlcParams(BaseModel):
    exchange: str
    symboltoken: str
    tradingsymbol: str
    interval: str = "ONE_DAY"
    fromdate: str
    todate: str

class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    feed_token: str

class LTPRequest(BaseModel):
    exchange: str = Field(..., description="NSE/BSE/NFO/MCX")
    tradingsymbol: str = Field(..., description="e.g., RELIANCE-EQ")
    symboltoken: str = Field(..., description="Angel symbol token as string")

class OrderParams(BaseModel):
    variety: str = "NORMAL"
    tradingsymbol: str
    symboltoken: str
    transactiontype: str  # BUY or SELL
    exchange: str = "NSE"
    ordertype: str = "MARKET"  # LIMIT/MARKET/SL/SL-M
    producttype: str = "INTRADAY"  # or DELIVERY/CARRYFORWARD
    duration: str = "DAY"
    price: Optional[str] = None
    triggerprice: Optional[str] = None
    quantity: str = "1"

# --- Helper to create and validate a client instance ---

def _require_client() -> SmartConnect:
    """
    Creates a SmartConnect instance using a saved session.
    Raises an exception if the session file is not found.
    """
    session_data = _load_session()
    if session_data is None:
        raise Exception("User is not logged in. Please login first.")

    api_key = os.getenv("ANGELONE_TRADING_API_KEY")
    if not api_key:
        raise ValueError("ANGELONE_TRADING_API_KEY not found in .env file.")
        
    sc = SmartConnect(api_key=api_key)
    sc.setAccessToken(session_data["access_token"])
    sc.setRefreshToken(session_data["refresh_token"])
    sc.setFeedToken(session_data["feed_token"])
    return sc

# --- MCP Tools ---
@mcp.tool()
def angel_get_ohlc(params: OhlcParams) -> Dict[str, Any]:
    """
    Fetch historical Open-High-Low-Close (OHLC) candle data for a symbol.
    This tool now takes a single object containing all necessary parameters.
    """
    sc = _require_client()
    # Convert the pydantic model to a dict for the SmartAPI call
    param_dict = params.model_dump()
    candle_data = sc.getCandleData(param_dict)
    if not candle_data or "data" not in candle_data:
        raise Exception(f"OHLC API failed: {candle_data}")
    return candle_data

@mcp.tool()
def angel_login(client_code: str, password: str, totp: str) -> LoginResponse:
    """
    Logs into Angel One, generates session tokens, and saves them to a file.
    This tool should be called first.
    """
    api_key = os.getenv("ANGELONE_TRADING_API_KEY")
    if not api_key:
        raise ValueError("ANGELONE_TRADING_API_KEY not found in .env file.")

    sc = SmartConnect(api_key=api_key)
    data = sc.generateSession(client_code, password, totp)

    if not data or "data" not in data or not data["data"]:
        raise Exception(f"Login failed. Broker response: {data.get('message', 'No message')}")
    
    refresh_token = data["data"]["refreshToken"]
    # The access token is automatically set by generateSession, but we need the feed token
    feed_token = sc.getfeedToken()

    session_data = {
        "access_token": sc.access_token,
        "refresh_token": refresh_token,
        "feed_token": feed_token,
    }
    _save_session(session_data)
    return LoginResponse(**session_data)

@mcp.tool()
def angel_get_ltp(req: LTPRequest) -> Dict[str, Any]:
    """Get the Last Traded Price (LTP) for a specific symbol."""
    sc = _require_client()
    ltp = sc.ltpData(req.exchange, req.tradingsymbol, req.symboltoken)
    if not ltp or "data" not in ltp or not ltp["data"]:
        raise Exception(f"LTP API failed: {ltp}")
    return ltp["data"]

@mcp.tool()
def angel_positions() -> Dict[str, Any]:
    """Get the user's current open positions for the day."""
    sc = _require_client()
    return sc.position()

@mcp.tool()
def angel_holdings() -> Dict[str, Any]:
    """Get the user's long-term holdings from their demat account."""
    sc = _require_client()
    return sc.holding()

@mcp.tool()
def angel_place_order(order: OrderParams) -> Dict[str, Any]:
    """Place a trade order (BUY or SELL)."""
    sc = _require_client()
    params = order.model_dump(exclude_none=True)
    resp = sc.placeOrder(params)
    return {"broker_response": resp}

@mcp.tool()
def angel_cancel_order(order_id: str, variety: str = "NORMAL") -> Dict[str, Any]:
    """Cancel a pending order by its unique order ID."""
    sc = _require_client()
    resp = sc.cancelOrder(order_id, variety)
    return {"broker_response": resp}

if __name__ == "__main__":
    import anyio
    print("[MCP] Entering run_stdio_async", flush=True)
    try:
        anyio.run(mcp.run_stdio_async)
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        print("[MCP] Exiting MCP server", flush=True)