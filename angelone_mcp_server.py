# angelone_mcp_server.py
import os
import time
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from SmartApi import SmartConnect
import json 
import os, sys
from dotenv import load_dotenv
load_dotenv()

print(f"[MCP START] PID={os.getpid()} ARGS={sys.argv}", flush=True)

SESSION_FILE = "angel_session.json"

def _save_session(data: dict):
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)

def _load_session() -> Optional[dict]:
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE) as f:
            return json.load(f)
    return None

mcp = FastMCP("angelone-mcp")

# Global client session (persist after login)
client: Optional[SmartConnect] = None

# --- Models ---
class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    feed_token: str

class LTPRequest(BaseModel):
    exchange: str = Field(..., description="NSE/BSE/NFO/MCX/etc.")
    tradingsymbol: str = Field(..., description="e.g., RELIANCE-EQ")
    symboltoken: str = Field(..., description="Angel symbol token as string")

class OrderParams(BaseModel):
    variety: str = "NORMAL"
    tradingsymbol: str
    symboltoken: str
    transactiontype: str  # BUY or SELL
    exchange: str = "NSE"
    ordertype: str = "MARKET"   # LIMIT/MARKET/SL/SL-M
    producttype: str = "INTRADAY"  # or DELIVERY/CARRYFORWARD
    duration: str = "DAY"
    price: Optional[str] = None
    triggerprice: Optional[str] = None
    quantity: str = "1"

# --- Helpers ---
session_data: Optional[dict] = None

def _require_client() -> SmartConnect:
    global session_data
    if session_data is None:
        session_data = _load_session()
    if session_data is None:
        raise Exception("Not logged in. Call angel_login first.")

    sc = SmartConnect(api_key=os.getenv("ANGELONE_TRADING_API_KEY"))
    sc.setAccessToken(session_data["access_token"])
    sc.setFeedToken(session_data["feed_token"])
    return sc

# --- MCP Tools ---
@mcp.tool()
def angel_login(client_code: str, password: str, totp: str) -> LoginResponse:
    global session_data
    sc = SmartConnect(api_key=os.getenv("ANGELONE_TRADING_API_KEY"))
    data = sc.generateSession(client_code, password, totp)

    if not data or "data" not in data or data["data"] is None:
        raise Exception(f"Login failed: {data}")
    
    refresh_token = data["data"]["refreshToken"]
    sc.generateToken(refresh_token)
    feed_token = sc.getfeedToken()

    # Save minimal session data instead of whole client
    session_data = {
        "access_token": sc.access_token,
        "refresh_token": refresh_token,
        "feed_token": feed_token,
    }
    _save_session(session_data)
    return LoginResponse(**session_data)

@mcp.tool()
def angel_get_ltp(req: LTPRequest) -> Dict[str, Any]:
    """
    Get last-traded-price for a symbol.
    """
    sc = _require_client()
    ltp = sc.ltpData(req.exchange, req.tradingsymbol, req.symboltoken)
    if not ltp or "data" not in ltp or ltp["data"] is None:
        raise Exception(f"LTP API failed: {ltp}")
    return ltp  # includes last_price etc.

@mcp.tool()
def angel_get_ohlc(exchange: str, tradingsymbol: str, symboltoken: str, interval: str = "FIVE_MINUTE", fromdate: Optional[str] = None, todate: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch recent OHLC candles for quick analysis.
    interval: ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE, TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY
    Dates as 'YYYY-MM-DD HH:MM' or per SmartAPI format.
    """
    sc = _require_client()
    params = {
        "exchange": exchange,
        "symboltoken": symboltoken,
        "interval": interval,
        "fromdate": fromdate,
        "todate": todate,
    }
    return sc.getCandleData(params)

@mcp.tool()
def angel_positions() -> Dict[str, Any]:
    """Get current positions."""
    sc = _require_client()
    return sc.position()

@mcp.tool()
def angel_holdings() -> Dict[str, Any]:
    """Get current holdings."""
    sc = _require_client()
    return sc.holding()

@mcp.tool()
def angel_place_order(order: OrderParams) -> Dict[str, Any]:
    """
    Place an order and return broker response incl. order id.
    """
    sc = _require_client()
    params = order.model_dump(exclude_none=True)
    resp = sc.placeOrder(params)
    return {"response": resp}

@mcp.tool()
def angel_cancel_order(order_id: str, variety: str = "NORMAL") -> Dict[str, Any]:
    """Cancel an order by id."""
    sc = _require_client()
    resp = sc.cancelOrder(order_id, variety)
    return {"response": resp}

@mcp.tool()
def angel_score_symbols(symbols: List[LTPRequest]) -> List[Dict[str, Any]]:
    """
    Heuristic ranker: pulls LTP for each symbol and returns a simplistic momentum/vol filter.
    Only returns clean fields (symbol, ltp, score, error).
    """
    sc = _require_client()
    out: List[Dict[str, Any]] = []

    for s in symbols:
        try:
            resp = sc.ltpData(s.exchange, s.tradingsymbol, s.symboltoken)
            if not resp or "data" not in resp or resp["data"] is None:
                raise Exception(f"LTP API returned no data: {resp}")

            last = float(resp["data"]["ltp"])
            out.append({
                "symbol": s.tradingsymbol,
                "ltp": last,
                "score": last,   # your scoring logic could be changed later
                "exchange": s.exchange,
            })
        except Exception as e:
            out.append({
                "symbol": s.tradingsymbol,
                "exchange": s.exchange,
                "error": str(e),
            })

        time.sleep(0.1)  # rate-limit

    # Sort only successful ones by score
    ranked = [o for o in out if "ltp" in o]
    ranked.sort(key=lambda x: x["score"], reverse=True)

    # Preserve errors at the end
    errors = [o for o in out if "error" in o]

    return ranked + errors


if __name__ == "__main__":
    import anyio
    print("[MCP] Entering run_stdio_async", flush=True)
try:
    anyio.run(mcp.run_stdio_async)
except Exception as e:
    import traceback; traceback.print_exc()
finally:
    print("[MCP] Exiting MCP server", flush=True)

    
