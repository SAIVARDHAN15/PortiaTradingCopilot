# app.py
import os
import sys
import json
import getpass
import pyotp
from dotenv import load_dotenv
from portia import Config, LLMProvider, Portia, McpToolRegistry
from pydantic import BaseModel, Field
from typing import List, Dict
from portia import PlanBuilderV2, StepOutput, Input

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client_code = os.getenv("ANGEL_CLIENT_CODE")
password = os.getenv("ANGEL_PASSWORD")
totp_secret = os.getenv("ANGEL_TOTP_SECRET")

# Generate TOTP dynamically
totp = pyotp.TOTP(totp_secret).now()


if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not found in environment. Set it in .env or environment variables.")

# 1) Portia config
config = Config.from_default(
    llm_provider=LLMProvider.GOOGLE,
    default_model="google/gemini-2.0-flash",
    google_api_key=GOOGLE_API_KEY,
)

# 2) MCP tool registry (stdio mode). This will spawn your MCP server script.
mcp_script = os.path.join(os.getcwd(), "angelone_mcp_server.py")
mcp_path = os.path.abspath("angelone_mcp_server.py")
print("Launching MCP via:", sys.executable, mcp_path)
angel_registry = McpToolRegistry.from_stdio_connection(
    server_name="angelone",
    command=sys.executable,  # venv Python
    args=[mcp_script]        # absolute script path
)

# 3) Create the Portia instance
portia = Portia(config=config, tools=angel_registry)
print("Loaded tools:", [t.name for t in angel_registry.get_tools()])

# --- Helper to run Portia and pretty print results ---
class Step(BaseModel):
    tool: str
    args: Dict[str, str]

class TradePlan(BaseModel):
    steps: List[Step]
    recommendation: str

from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class FlexibleTradeResponse(BaseModel):
    recommendation: Optional[str] = None
    reasoning: Optional[str] = None
    current_price: Optional[float] = None
    symbol: Optional[str] = None
    actions_taken: Optional[List[str]] = None
    error: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None

def run_portia_and_print(prompt: str):
    try:
        print("\n>>> Sending structured prompt to Portia...")
        
        result = portia.run(
            query=prompt,
            structured_output_schema=FlexibleTradeResponse
        )
        
        if result:
            print("✅ Structured response:")
            print(result.model_dump_json(indent=2))
        else:
            print("❌ Portia returned no response.")
            
    except Exception as e:
        print("❌ Error running Portia with structured output:", str(e))
        print("⚠️  Falling back to unstructured mode...")
        
        # Fallback to unstructured mode
        try:
            result = portia.run(query=prompt)
            if result:
                print("✅ Fallback response:")
                if hasattr(result, 'outputs') and hasattr(result.outputs, 'final_output'):
                    print(result.outputs.final_output.value)
                else:
                    print(result)
        except Exception as fallback_error:
            print("❌ Fallback also failed:", str(fallback_error))



# --- CLI flows ---
class LtpRecommendation(BaseModel):
    recommendation: str = Field(..., description="BUY, SELL, or HOLD with reason")
    stoploss: float = Field(..., description="Stoploss price")
    target: float = Field(..., description="Target price (approx)")

from portia import PlanBuilderV2, StepOutput, Input

def login_and_suggest_flow():
    """
    Logs into Angel One using MCP tool, fetches LTP for a given symbol,
    and returns a structured recommendation using PlanBuilderV2.
    """
    print("\n== Login + LTP suggestion flow (via PlanBuilderV2) ==")

    # Get credentials from environment
    client_code = os.getenv("ANGEL_CLIENT_CODE")
    password = os.getenv("ANGEL_PASSWORD")
    totp_secret = os.getenv("ANGEL_TOTP_SECRET")

    if not client_code or not password or not totp_secret:
        print("❌ Missing credentials in .env. Please add ANGEL_CLIENT_CODE, ANGEL_PASSWORD, ANGEL_TOTP_SECRET.")
        return

    # Generate TOTP dynamically
    totp = pyotp.TOTP(totp_secret).now()

    # Get symbol details from user
    symbol = input("Enter tradingsymbol to check (e.g., RELIANCE-EQ): ").strip()
    exchange = input("Exchange (NSE/BSE) [default NSE]: ").strip() or "NSE"
    symboltoken = input("Enter Angel symboltoken (if known) or leave blank: ").strip()

    # --- Build the plan using PlanBuilderV2 ---
    builder = PlanBuilderV2("Login and get LTP for analysis")

    plan = (
        builder
        # Step 1: Login
        .invoke_tool_step(
            step_name="Login to Angel One",
            tool="mcp:angelone:angel_login",
            args={
                "client_code": client_code,
                "password": password,
                "totp": totp
            }
        )
        .invoke_tool_step(
            step_name="Fetch LTP",
            tool="mcp:angelone:angel_get_ltp",
            args={
                "req": {
                    "exchange": exchange,
                    "tradingsymbol": symbol,
                    "symboltoken": symboltoken
                }
            }
        )
        # Step 3: Generate recommendation using LLM
        .llm_step(
            task=(
                "Based on the LTP (and optionally OHLC), "
                "provide a recommendation (BUY/SELL/HOLD) with reasoning, stoploss, and 1:2 target."
            ),
            inputs=[StepOutput("Fetch LTP")],  # Pass LTP result to LLM
            output_schema=LtpRecommendation
        )
        # Final Output
        .final_output(output_schema=LtpRecommendation)
        .build()
    )

    print("\n>>> Executing plan with Portia...\n")

    # --- Execute the plan ---
    try:
        plan_run = portia.run_plan(plan)
        result = plan_run.outputs.final_output.value
        print("\n✅ Recommendation (Structured Output):")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"❌ Error executing plan: {e}")



def analyze_symbols_flow():
    """
    Score/rank a list of symbols using the MCP score tool or by fetching LTPs and OHLC.
    """
    print("\n== Analyze & rank symbols flow ==")
    raw = input("Enter symbols separated by commas (e.g., RELIANCE-EQ, TCS-EQ, INFY-EQ): ").strip()
    symbols = [s.strip() for s in raw.split(",") if s.strip()]
    exchange = input("Exchange (NSE/BSE) [default NSE]: ").strip() or "NSE"

    # Prompt asks Portia to call angel_get_ltp / angel_get_ohlc for each symbol and rank them.
    # If your MCP implements angel_score_symbols, Portia may prefer that.
    symbols_block = json.dumps([{"exchange": exchange, "tradingsymbol": s, "symboltoken": ""} for s in symbols])

    prompt = f"""
You are connected to Angel One MCP tools.

Task:
- For each symbol in {symbols_block}, call `angel_get_ltp` (and optionally `angel_get_ohlc` for recent 5-minute candles),
- Compute a simple score using momentum (last vs previous candle) and volatility,
- Return a JSON array of objects: {{symbol, ltp, score, recommendation}} sorted by score descending.
- Keep recommendations among ["STRONG BUY", "BUY", "HOLD", "SELL"].

Do not place any orders yet. Show the tool calls and the final ranked JSON.
"""
    run_portia_and_print(prompt)


def review_portfolio_flow():
    """
    Ask Portia to fetch holdings/positions, compute P/L with current LTPs, and give advice.
    """
    print("\n== Portfolio review flow ==")

    prompt = """
        You are connected to Angel One MCP tools.

        1) Call `angel_holdings` and `angel_positions`.
        2) If BOTH holdings and positions are empty, immediately return:
        "No active holdings or positions found."
        3) Otherwise, for each holding/position, call `angel_get_ltp` to fetch current price.
        4) Compute P/L percentage vs average buy price or cost.
        5) For any position with P/L <= -3% (loss) or P/L >= +5% (profit), flag it with a suggested action:
        - if loss <= -3% -> "CONSIDER TRIM/SELL" (explain in one sentence)
        - if profit >= +5% -> "CONSIDER BOOKING PROFIT" (explain in one sentence)
        6) Return a concise table in JSON: [{symbol, qty, avg_price, ltp, pl_percent, action, reason}]

        Do NOT place any orders.
        """

    run_portia_and_print(prompt)


def place_order_flow():
    """
    Place an actual order after explicit user confirmation. This flow will ask the user
    for the same login credentials (if needed) and order params; it will require explicit confirmation.
    """
    print("\n== Place order flow (explicit confirmation required) ==")
    # Get login credentials to ensure the session is active; if already logged in earlier, the MCP may reuse token.
    client_code = input("Enter Angel One client_code (or press Enter if already logged in): ").strip()
    if client_code:
        password = getpass.getpass("Enter Angel One password (hidden): ").strip()
        totp = getpass.getpass("Enter current TOTP code (from your authenticator): ").strip()
    else:
        password = totp = ""

    symbol = input("tradingsymbol (e.g., RELIANCE-EQ): ").strip()
    exchange = input("Exchange (NSE/BSE) [default NSE]: ").strip() or "NSE"
    symboltoken = input("symboltoken (optional): ").strip()
    side = input("Transaction type BUY or SELL [default BUY]: ").strip().upper() or "BUY"
    qty = input("Quantity [default 1]: ").strip() or "1"
    product = input("Product type (INTRADAY/DELIVERY) [default INTRADAY]: ").strip().upper() or "INTRADAY"
    ordertype = input("Order type (MARKET/LIMIT) [default MARKET]: ").strip().upper() or "MARKET"

    # Price only if LIMIT
    price = ""
    if ordertype == "LIMIT":
        price = input("Limit price: ").strip()

    print("\nReview the order below:")
    print(f"Symbol: {symbol} | Exchange: {exchange} | Side: {side} | Qty: {qty} | Product: {product} | Type: {ordertype} | Price: {price or 'MKT'}")
    confirm = input("Type 'YES' to CONFIRM and place this order: ").strip()
    if confirm != "YES":
        print("Order cancelled by user.")
        return

    # Build prompt that does an optional login and then places the order
    login_block = ""
    if client_code:
        login_block = f'Call `angel_login` with client_code="{client_code}", password="{password}", totp="{totp}". Then '

    order_params = {
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "symboltoken": symboltoken or None,
        "transactiontype": side,
        "exchange": exchange,
        "ordertype": ordertype,
        "producttype": product,
        "duration": "DAY",
        "price": price or None,
        "quantity": qty,
    }

    # Build a small natural language request for Portia that instructs the MCP to place an order.
    # We pass the order params as explicit values for the `angel_place_order` tool.
    order_json = json.dumps({k: v for k, v in order_params.items() if v is not None})

    prompt = f"""
You are connected to Angel One MCP tools.

{login_block}Then call `angel_place_order` with the following order parameters:
{order_json}

After placing the order, return the broker response and a human-friendly summary:
- order id (if any),
- status (success/failure),
- executed qty / average price (if available).

Also return the tool call trace.
"""

    run_portia_and_print(prompt)


# --- Minimal CLI ---
def main():
    print("=== Portia Trading Agent CLI ===")
    print("Ensure angelone_mcp_server.py exists and that ANGELONE_TRADING_API_KEY is set in your environment.")
    while True:
        print("\nChoose an action:")
        print("1) Login + check LTP + suggest buy/sell (no order placement)")
        print("2) Analyze / rank multiple symbols")
        print("3) Review portfolio (positions & holdings)")
        print("4) Place an order (requires explicit YES confirmation)")
        print("5) Exit")

        choice = input("Enter choice [1-5]: ").strip()
        if choice == "1":
            login_and_suggest_flow()
        elif choice == "2":
            analyze_symbols_flow()
        elif choice == "3":
            review_portfolio_flow()
        elif choice == "4":
            place_order_flow()
        elif choice == "5":
            print("Goodbye.")
            sys.exit(0)
        else:
            print("Invalid choice. Please enter 1..5.")


if __name__ == "__main__":
    main()
