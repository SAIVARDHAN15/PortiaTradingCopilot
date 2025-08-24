# api.py
import os
import sys
import sqlite3
import pyotp
import pandas as pd
import pandas_ta as ta
import requests
import re
import sqlite3
import json
from nsepython import nsefetch
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from json_repair import repair_json
from portia.plan_run import PlanRunState
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from portia import (
    Config,
    LLMProvider,
    Portia,
    McpToolRegistry,
    PlanBuilderV2,
    StepOutput,
)

# --- Initial Setup ---
load_dotenv()

# FastAPI App Initialization
app = FastAPI(
    title="Portia Trading Agent API",
    description="Backend server for the Streamlit Trading Agent UI",
)

# CORS Middleware to allow requests from the Streamlit frontend
# (Adjust origin if your Streamlit app is hosted elsewhere)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Portia AI Setup ---

# 1) Portia config
config = Config.from_default(
    llm_provider=LLMProvider.GOOGLE,
    default_model="google/gemini-2.0-flash", # Using a powerful and fast model
    google_api_key=os.getenv("GOOGLE_API_KEY"),
)

# 2) MCP tool registry connection
mcp_script_path = os.path.abspath("angelone_mcp_server.py")
print(f"Attempting to launch MCP server script at: {mcp_script_path}")

if not os.path.exists(mcp_script_path):
    raise FileNotFoundError(f"MCP server script not found at {mcp_script_path}")

angel_registry = McpToolRegistry.from_stdio_connection(
    server_name="angelone",
    command=sys.executable,  
    args=[mcp_script_path],
)

# 3) Create the Portia instance
portia = Portia(config=config, tools=angel_registry)
print("✅ Portia initialized successfully with Angel One tools.")
print("Loaded tools:", [t.name for t in angel_registry.get_tools()])

# --- API Pydantic Models ---
class Intent(BaseModel):
    intent: str = Field(..., description="The user's primary goal. Must be one of: 'get_ltp', 'get_ohlc', 'analyze_stock', 'analyze_portfolio', 'get_market_movers', 'place_order', 'cancel_order', 'general_query'.")
    tradingsymbol: Optional[str] = Field(None, description="The stock symbol, if mentioned (e.g., 'RELIANCE-EQ').")
    order_id: Optional[str] = Field(None, description="The order ID for cancellation, if mentioned.")
    interval: Optional[str] = Field("ONE_DAY", description="The candle interval, if mentioned (e.g., 'FIVE_MINUTE', 'ONE_DAY'). Defaults to 'ONE_DAY'.")
    fromdate: Optional[str] = Field(None, description="The start date for historical data, if mentioned (YYYY-MM-DD HH:MM).")
    todate: Optional[str] = Field(None, description="The end date for historical data, if mentioned (YYYY-MM-DD HH:MM).")
class OhlcParams(BaseModel):
    exchange: str
    symboltoken: str
    tradingsymbol: str
    interval: str = "ONE_DAY"
    fromdate: str
    todate: str
class LoginRequest(BaseModel):
    client_code: str
    password: str
    totp: str

class OrderParamsParser(BaseModel):
    tradingsymbol: str
    transactiontype: str
    quantity: str
    producttype: str
    ordertype: str

class ChatRequest(BaseModel):
    message: str
    
class OrderExecutionRequest(BaseModel):
    order_params: Dict[str, Any]

class ApiResponse(BaseModel):
    status: str = "success"
    content: Optional[str] = None
    data: Optional[Any] = None
    type: str = "text"  # Used by UI to determine how to render (text, json, dataframe, confirmation)

# --- Helper Functions ---
def get_symbol_details(tradingsymbol: str):
    """Lookup symbol details in instruments.db with case-insensitive and -EQ handling."""
    conn = sqlite3.connect("instruments.db")
    cursor = conn.cursor()

    sym = tradingsymbol.strip().upper()

    # 1. Try exact match
    cursor.execute(
        "SELECT exchange, tradingsymbol, symboltoken FROM instruments WHERE tradingsymbol = ? COLLATE NOCASE",
        (sym,)
    )
    row = cursor.fetchone()

    # 2. Try with "-EQ" suffix if not found
    if not row and not sym.endswith("-EQ"):
        cursor.execute(
            "SELECT exchange, tradingsymbol, symboltoken FROM instruments WHERE tradingsymbol = ? COLLATE NOCASE",
            (sym + "-EQ",)
        )
        row = cursor.fetchone()

    # 3. Try fallback fuzzy match on name if still not found
    if not row:
        try:
            cursor.execute(
                "SELECT exchange, tradingsymbol, symboltoken FROM instruments WHERE name LIKE ? COLLATE NOCASE",
                (f"%{sym}%",)
            )
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass

    conn.close()

    if not row:
        raise ValueError(f"Symbol {tradingsymbol} not found in instruments.db")

    return {"exchange": row[0], "tradingsymbol": row[1], "symboltoken": row[2]}

def build_order_payload(order: dict, details: dict) -> dict:
    """Merge user-provided order params with broker symbol details and normalize fields."""
    merged = {**order}
    # Attach required fields from details
    merged["symboltoken"] = details.get("symboltoken")
    merged["exchange"] = details.get("exchange")
    # Prefer canonical tradingsymbol from details if available
    if details.get("tradingsymbol"):
        merged["tradingsymbol"] = details["tradingsymbol"]

    # Normalize a few common fields Angel expects
    for key in ("transactiontype", "producttype", "ordertype", "variety", "duration"):
        if key in merged and isinstance(merged[key], str):
            merged[key] = merged[key].upper()

    # Defaults if missing
    merged.setdefault("variety", "NORMAL")
    merged.setdefault("duration", "DAY")
    if "quantity" in merged:
        merged["quantity"] = str(merged["quantity"])  # SmartAPI expects string
    return merged

def parse_json_from_llm_output(llm_string: str):
    """
    Cleans and parses JSON from LLM output.
    Handles:
      - Markdown code fences (```json ... ```)
      - Stray backticks
      - Truncated/incomplete JSON (via json-repair)
    """
    # 1. Remove code fences
    cleaned = re.sub(r"```(?:json)?|```", "", llm_string).strip()

    try:
        # 2. Try direct parse
        return json.loads(cleaned)

    except json.JSONDecodeError:
        # 3. Attempt repair if malformed
        try:
            repaired = repair_json(cleaned)
            return json.loads(repaired)
        except Exception as e:
            # Bubble up if unrecoverable
            raise e

def analyze_stock_technicals(ohlc_data: List[List[Any]]) -> Dict[str, Any]:
    # Check if input is missing
    if not ohlc_data:
        return {"error": "No OHLC data provided."}

    # If input is a string, try to parse JSON
    if isinstance(ohlc_data, str):
        import json
        try:
            ohlc_data = json.loads(ohlc_data)
        except Exception:
            return {"error": "Unsupported OHLC data format. Expected list of lists, got string."}

    # Validate structure
    if not isinstance(ohlc_data, (list, tuple)) or not all(isinstance(row, (list, tuple)) for row in ohlc_data):
        return {"error": "Invalid OHLC format. Expected list of lists."}

    if len(ohlc_data) < 50:
        return {"error": "Not enough historical data to perform analysis."}

    # Build DataFrame safely
    try:
        df = pd.DataFrame(ohlc_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
    except Exception as e:
        return {"error": f"Failed to construct DataFrame: {str(e)}"}

    # Calculate indicators
    df.ta.rsi(append=True)
    df.ta.macd(append=True)
    df.ta.sma(length=50, append=True)
    if len(df) >= 200:
        df.ta.sma(length=200, append=True)

    latest = df.iloc[-1]

    # Trend check
    trend = "unknown"
    if 'SMA_200' in df.columns and 'SMA_50' in df.columns:
        if latest['SMA_50'] > latest['SMA_200']:
            trend = "uptrend"
        else:
            trend = "downtrend"

    return {
        "rsi": round(latest.get('RSI_14', 0), 2),
        "macd_signal": "bullish" if latest.get('MACD_12_26_9', 0) > latest.get('MACDh_12_26_9', 0) else "bearish",
        "trend": trend
    }


import requests
from typing import List, Dict

import requests
from typing import List, Dict

import requests, time
from typing import List, Dict

def scrape_market_movers() -> List[Dict[str, str]]:
    try:
        url = "https://www.nseindia.com/api/live-analysis-variations?index=gainers"
        data = nsefetch(url)

        if not isinstance(data, dict):
            return [{"error": f"Unexpected response format: {type(data)}"}]

        movers_raw = None
        for key in ("data", "DATA", "NIFTY", "NIFTY50"):
            if key in data and isinstance(data[key], list):
                movers_raw = data[key][:5]
                break

        if not movers_raw:
            keys = list(data.keys())
            return [{"error": f"No valid movers data found. Keys: {keys}"}]

        movers = [
            {
                "symbol": m.get("symbol", "N/A"),
                "ltp": m.get("ltp", "N/A"),
                "change_percent": m.get("netPrice", "N/A")
            }
            for m in movers_raw
        ]
        return movers

    except Exception as e:
        return [{"error": f"Failed to fetch market movers: {e}"}]

    

def create_stock_analysis_plan(tradingsymbol: str):
    builder = PlanBuilderV2("Analyze Stock Technicals"); 
    today = datetime.now()
    days_to_fetch = 250
    start_date = today - timedelta(days=days_to_fetch)
    return (builder
        .function_step(step_name="GetDetails", function=get_symbol_details, args={"tradingsymbol": tradingsymbol})
        .llm_step(
            step_name="PrepareOhlcArgs",
            task=f"""
            Based on the details from the previous step, prepare the arguments for the angel_get_ohlc tool.
            The interval should be 'ONE_DAY'.
            The fromdate should be '{start_date.strftime('%Y-%m-%d %H:%M')}'.
            The todate should be '{today.strftime('%Y-%m-%d %H:%M')}'.
            """,
            inputs=[StepOutput("GetDetails")],
            output_schema=OhlcParams
        )
        .invoke_tool_step(
            step_name="GetHistory",
            tool="mcp:angelone:angel_get_ohlc",
            args={"params": StepOutput("PrepareOhlcArgs")}
        )
        .llm_step(
            step_name="ExtractData",
            task="From the previous step's JSON output, extract and return only the value of the 'data' key. Ensure the output is a complete and valid JSON array of arrays.",
            inputs=[StepOutput("GetHistory")]
        )
        .function_step(
            step_name="ParseJson",
            function=parse_json_from_llm_output,
            args={"llm_string": StepOutput("ExtractData")}
        )
        .function_step(
            step_name="CalculateTechnicals",
            function=analyze_stock_technicals,
            args={"ohlc_data": StepOutput("ParseJson")}
        )
        .llm_step(task="""You are a neutral financial analyst. Based on the provided indicators (RSI, MACD, Trend), give a balanced analysis. Conclude with a clear disclaimer that this is not financial advice.""", inputs=[StepOutput("CalculateTechnicals")])
        .final_output().build())

def is_user_logged_in() -> bool:
    """Checks if the angel_session.json file exists."""
    return os.path.exists("angel_session.json")

def create_ohlc_plan(tradingsymbol: str, interval: str, fromdate: str, todate: str):
    """Builds a plan to fetch historical OHLC data."""
    builder = PlanBuilderV2("Fetch Historical OHLC Data")
    return (builder
        .function_step(
            step_name="GetDetails",
            function=get_symbol_details,
            args={"tradingsymbol": tradingsymbol}
        )
        .invoke_tool_step(
            step_name="GetHistory",
            tool="mcp:angelone:angel_get_ohlc",
            args={
                "exchange": StepOutput("GetDetails").get_value("exchange"),
                "symboltoken": StepOutput("GetDetails").get_value("symboltoken"),
                "tradingsymbol": tradingsymbol,
                "interval": interval,
                "fromdate": fromdate,
                "todate": todate,
            }
        )
        .llm_step(
            task="The user has requested historical data. Format the candle data from the previous step into a clean, readable list or table. Mention the symbol and the time interval.",
            inputs=[StepOutput("GetHistory")]
        )
        .final_output().build())

# The definitions for the 'create_..._plan' functions are here
def create_ltp_plan(tradingsymbol: str):
    """Builds a plan to get the LTP for a symbol."""
    builder = PlanBuilderV2("Fetch Last Traded Price")
    return (builder
        .function_step(
            step_name="GetDetails",
            function=get_symbol_details,  
            args={"tradingsymbol": tradingsymbol}
        )
        .invoke_tool_step(
            step_name="GetLTP",
            tool="mcp:angelone:angel_get_ltp",
            args={"req": StepOutput("GetDetails")}
        )
        .llm_step(
            task="Summarize the LTP data clearly for the user. Show open, high, low, close and (LTP) prices in a clean format.",
            inputs=[StepOutput("GetLTP")]
        )
        .final_output().build())


def create_cancel_order_plan(order_id: str):
    builder = PlanBuilderV2("Cancel an Order")
    return (builder
        .invoke_tool_step(step_name="CancelOrder", tool="mcp:angelone:angel_cancel_order", args={"order_id": order_id})
        .llm_step(task="Confirm to the user whether the order cancellation was successful based on the broker response.", inputs=[StepOutput("CancelOrder")])
        .final_output().build())


def create_portfolio_plan():
    """
    Creates a reliable plan to fetch both holdings and positions and summarize them.
    """
    builder = PlanBuilderV2("Fetch and review user's portfolio")
    plan = (
        builder
        .invoke_tool_step(
            step_name="GetHoldings",
            tool="mcp:angelone:angel_holdings"
        )
        .invoke_tool_step(
            step_name="GetPositions",
            tool="mcp:angelone:angel_positions"
        )
        .llm_step(
            task="Summarize the user's portfolio. First list their long-term holdings from GetHoldings, then list their intraday positions from GetPositions. If either is empty, state that. Present the data clearly.",
            inputs=[StepOutput("GetHoldings"), StepOutput("GetPositions")]
        )
        .final_output()
        .build()
    )
    return plan


def create_order_execution_plan(order_params: dict):
    """Builds a robust, multi-step plan to execute a trade."""
    builder = PlanBuilderV2("Fetch Symbol Details and Place Order")
    return (builder
        # Step 1: Always get the latest symbol details first.
        .function_step(
            step_name="GetDetails",
            function=get_symbol_details,
            args={"tradingsymbol": order_params.get("tradingsymbol")}
        )
        # Step 2: Place the order using a combination of original params and details from Step 1.
        .function_step(
            step_name="BuildOrderPayload",
            function=build_order_payload,
            args={
                "order": order_params,                 
                "details": StepOutput("GetDetails")    
            }
        )
        # 3) Place the order using the merged payload
        .invoke_tool_step(
            step_name="PlaceOrder",
            tool="mcp:angelone:angel_place_order",
            args={"order": StepOutput("BuildOrderPayload")}
        )
        .llm_step(
            task="Summarize the result of the order placement. State clearly if it was successful and include the order ID from the broker_response.",
            inputs=[StepOutput("PlaceOrder")]
        )
        .final_output().build())

# --- API Endpoints ---
@app.get("/", summary="Health check endpoint")
def read_root():
    """Simple health check to confirm the server is running."""
    return {"status": "Portia API is running"}


class LoginRequest(BaseModel):
    client_code: str
    password: str


@app.post("/login", response_model=ApiResponse, summary="Login to Angel One")
async def login(request: LoginRequest):
    """
    Logs the user into Angel One by automatically generating the TOTP.
    """
    print(f"Received login request for client code: {request.client_code}")

    try:
        
        totp_secret = os.getenv("ANGEL_TOTP_SECRET")
        if not totp_secret:
            raise ValueError("ANGEL_TOTP_SECRET not found in .env file.")
        
        totp_code = pyotp.TOTP(totp_secret).now()
        print(f"[DEBUG] Generated TOTP code: {totp_code}")
        

        builder = PlanBuilderV2("Login to Angel One Broker")
        plan = (
            builder
            .invoke_tool_step(
                step_name="Login",
                tool="mcp:angelone:angel_login",
                args={
                    "client_code": request.client_code,
                    "password": request.password,
                    "totp": totp_code, 
                }
            )
            .build()
        )

        plan_run = await portia.arun_plan(plan)
        final_output_value = plan_run.outputs.final_output.value

        if plan_run.state == PlanRunState.FAILED:
            error_message = str(final_output_value)
            print(f"Login plan failed with message: {error_message}")
            raise Exception(error_message)

        print("Login successful:", final_output_value)
        return ApiResponse(content="✅ Login successful! You can now start chatting.")

    except Exception as e:
        print(f"Login failed: {e}")
        raise HTTPException(status_code=400, detail=f"Login failed: {str(e)}")
        
    except Exception as e:
        print(f"Login failed: {e}")
        raise HTTPException(status_code=400, detail=f"Login failed: {str(e)}")

# In api.py

# Replace the entire chat function with this one

# In api.py

@app.post("/chat", response_model=ApiResponse)
async def chat(request: ChatRequest):
    if not os.path.exists("angel_session.json"):
        return ApiResponse(status="error", content="Please log in first.", type="error")

    # --- ARCHITECTURAL NOTE  ---
    # The agent initially used a fully autonomous planning approach using `portia.arun()`.
    # This relied on the LLM to both create and execute a plan from the user's raw query.
    #
    # REASON FOR CHANGE:
    # The autonomous planner proved to be unreliable, frequently failing to generate a valid
    # plan (resulting in `StepsOrError` validation exceptions) for even simple queries.
    # This led to a poor user experience and 500 errors.
    #
    # The current "Classify Then Execute" pattern was implemented for superior reliability
    # and performance. It uses the LLM for its strength (language understanding) and
    # `PlanBuilderV2` for its strength (guaranteed, reliable execution).
    # --- END OF NOTE ---

    try:
        # STEP 1: CLASSIFY INTENT using an LLM-only plan
    
        classification_task = f"""
        Analyze the user's query to determine their intent and extract relevant entities. Respond ONLY with a JSON object matching the required schema.

        **Intent Definitions:**
        - 'get_ltp': User wants the current Last Traded Price of a specific stock.
        - 'analyze_stock': User wants a detailed technical analysis of a single stock to help decide whether to buy or sell.
        - 'get_portfolio': User wants a simple summary list of their current stocks.
        - 'analyze_portfolio': User wants a detailed technical analysis of all stocks in their portfolio.
        - 'get_market_movers': User wants to see the top-performing (gaining) stocks of the day.
        - 'place_order': User wants to buy or sell a stock.
        - 'cancel_order': User wants to cancel an existing order by its ID.
        - 'general_query': Use this if no other intent fits.

        **Examples:**
        - User Query: "what is the price of reliance?" -> {{"intent": "get_ltp", "tradingsymbol": "RELIANCE-EQ"}}
        - User Query: "should I buy suzlon?" -> {{"intent": "analyze_stock", "tradingsymbol": "SUZLON-EQ"}}
        - User Query: "show me my holdings" -> {{"intent": "get_portfolio"}}
        - User Query: "how are my stocks doing today?" -> {{"intent": "analyze_portfolio"}}
        - User Query: "top gainers?" -> {{"intent": "get_market_movers"}}
        - User Query: "cancel my order 12345" -> {{"intent": "cancel_order", "order_id": "12345"}}

        **User Query to Classify:**
        "{request.message}"
        """
        classification_builder = PlanBuilderV2("Classify User Intent")
        classification_plan = (classification_builder
            .llm_step(
                task=classification_task,
                output_schema=Intent
            )
            .final_output()
            .build()
        )
        plan_run = await portia.arun_plan(classification_plan)
        if plan_run.state == PlanRunState.FAILED:
            raise Exception(f"Could not understand intent. {plan_run.outputs.final_output.value}")
        intent_result = plan_run.outputs.final_output.value
        
        
        print(f"[INFO] Classified Intent: {intent_result.intent}")
        plan = None

        # STEP 2: ROUTE TO THE CORRECT RELIABLE PLAN
        if intent_result.intent == "get_ltp":
            if not intent_result.tradingsymbol: return ApiResponse(content="Please specify which stock you'd like me to check.", type="text")
            plan = create_ltp_plan(intent_result.tradingsymbol)
        elif intent_result.intent == "get_portfolio":
            plan = create_portfolio_plan()
        elif intent_result.intent == "cancel_order":
            if not intent_result.order_id: return ApiResponse(content="Please provide the order ID you wish to cancel.", type="text")
            plan = create_cancel_order_plan(intent_result.order_id)
        elif intent_result.intent == "place_order":
            
            parsing_builder = PlanBuilderV2("Parse Order Parameters")
            parsing_plan = (parsing_builder
                .llm_step(
                    task=f"From the user request: \"{request.message}\", extract parameters for an order.",
                    output_schema=OrderParamsParser
                )
                .final_output()
                .build()
            )
            parsing_run = await portia.arun_plan(parsing_plan)
            if parsing_run.state == PlanRunState.FAILED:
                raise Exception(f"Could not parse order details. {parsing_run.outputs.final_output.value}")
            order_params = parsing_run.outputs.final_output.value
            return ApiResponse(status="pending_confirmation", content="Please review and confirm the order details below.", data=order_params.model_dump(), type="confirmation")
        elif intent_result.intent == "get_ohlc":
            default_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
            default_to = datetime.now().strftime("%Y-%m-%d %H:%M")
            plan = (
                PlanBuilderV2("Get OHLC Data")
                .invoke_tool_step(
                    step_name="get_OHLC",
                    tool="mcp:angelone:angel_get_ohlc",  # invoke MCP tool by name
                    args={
                        "params": {
                            "exchange": "NSE",  # or resolve dynamically from instruments.db
                            "tradingsymbol": intent_result.tradingsymbol,
                            "symboltoken": get_symbol_details(intent_result.tradingsymbol).get("symboltoken"),
                            "interval": intent_result.interval or "ONE_DAY",
                            "fromdate": intent_result.fromdate or default_from,
                            "todate": intent_result.todate or default_to,
                        }
                    },
                )
                .llm_step(
                    task=(
                    "You are a financial data analyst. "
                    "Take the OHLC (Open, High, Low, Close, Volume) data provided. "
                    "1. Create a markdown table with columns: Date | Open | High | Low | Close | Volume. "
                    "2. Write a short trend analysis (2-3 sentences) highlighting major price movements, "
                    "trends (upward, downward, sideways), and any notable spikes in volume. "
                    "3. Keep the tone clear, concise, and professional. "
                    "4. Do not add extra commentary or unrelated text. "
                    "Return only markdown-formatted output."
                ),
                inputs=[StepOutput("get_OHLC")],
                )
                .final_output()
                .build()
            )
            result = await portia.arun_plan(plan)
            final_output = result.outputs.final_output.value
            
            return ApiResponse(content=final_output, type="text")

        elif intent_result.intent == "analyze_portfolio":
            plan = (
                PlanBuilderV2("AnalyzePortfolio")
                .invoke_tool_step(
                    step_name="GetHoldings",
                    tool="mcp:angelone:angel_holdings",
                )
                .llm_step(
                    task=(
                        "You are a financial assistant. Analyze this portfolio holdings data and provide:\n"
                        "1. A summary of total investment, current value, and overall gain/loss.\n"
                        "2. Top 3 best performing holdings and bottom 3 worst performing.\n"
                        "3. Sector or industry diversification insights (if possible).\n"
                        "4. Risk level and improvement suggestions.\n\n"
                        "Format the results in Markdown, with:\n"
                        "- A clean summary table of holdings (Symbol | Qty | Avg Price | LTP | Current Value | P&L).\n"
                        "- A text explanation of trends and insights."
                    ),
                    inputs=[StepOutput("GetHoldings")],
                )
                .final_output()
                .build()
            )
            holdings_run = await portia.arun_plan(plan)
            holdings = holdings_run.outputs.final_output.value.get('data')
            if not holdings: return ApiResponse(content="You have no holdings to analyze.", type="text")
            all_analyses = [f"Analysis for {h['tradingsymbol']}:\n{(await portia.arun_plan(create_stock_analysis_plan(h['tradingsymbol']))).outputs.final_output.value}\n---" for h in holdings]
            summary_plan = PlanBuilderV2("Summarize").llm_step("Summarize", "Summarize all individual stock analyses into a portfolio overview.", inputs={"analyses": "\n".join(all_analyses)}).final_output().build()
            summary_run = await portia.arun_plan(summary_plan)
            return ApiResponse(content=summary_run.outputs.final_output.value, type="text")
        elif intent_result.intent == "analyze_stock":
            if not intent_result.tradingsymbol: return ApiResponse(content="Please specify which stock to analyze.", type="text")
            plan = create_stock_analysis_plan(intent_result.tradingsymbol)
        elif intent_result.intent == "get_market_movers":
            plan = (
            PlanBuilderV2("Get Market Movers")
                .function_step(
                    step_name="Scrape",
                    function=scrape_market_movers
                )
                .llm_step(
                    step_name="Format",
                    task="Format this data into a clean list for the user.",
                    inputs=[StepOutput("Scrape")]
                )
                .final_output()
                .build()
)
        else: # general_query
            return ApiResponse(content="I can currently analyze stocks, portfolios, market movers, fetch prices, and handle orders. Please try one of those actions.", type="text")

        # STEP 3: EXECUTE THE CHOSEN PLAN
        if plan:
            plan_run = await portia.arun_plan(plan)
            if plan_run.state == PlanRunState.FAILED: raise Exception(str(plan_run.outputs.final_output.value))
            return ApiResponse(content=plan_run.outputs.final_output.value, type="text")
        else:
            raise Exception("No valid plan was selected for execution.")

    except Exception as e:
        print(f"Error during chat processing: {e}")
        error_message = f"An error occurred: {str(e)}".split("detail=")[-1].strip("'")
        raise HTTPException(status_code=500, detail=error_message)


@app.post("/execute_order", response_model=ApiResponse)
async def execute_order(request: OrderExecutionRequest):
    if not os.path.exists("angel_session.json"):
        raise HTTPException(status_code=401, detail="You are not logged in.")
        
    print(f"Executing confirmed order with robust plan: {request.order_params}")
    
    try:
        # Build and run the order execution plan
        order_plan = create_order_execution_plan(request.order_params)
        plan_run = await portia.arun_plan(order_plan)

        # Check if execution failed
        if plan_run.state == PlanRunState.FAILED:
            error_msg = str(plan_run.outputs.final_output.value)
            raise HTTPException(status_code=400, detail=f"Order execution failed: {error_msg}")
        
        
        summary = plan_run.outputs.final_output.value

        # Return structured ApiResponse
        return ApiResponse(
            status="success",
            content="✅ Order executed successfully!",
            data=summary,
            type="execution_result"
        )
        
    except HTTPException:
        # Re-raise cleanly if already an HTTPException
        raise
    except Exception as e:
        print(f"Order execution failed: {e}")
        raise HTTPException(status_code=400, detail=f"Order execution failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)