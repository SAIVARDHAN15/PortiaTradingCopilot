# api.py
import os
import sys
import json
import pyotp
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
    allow_origins=["*"],  # Allows all origins
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
    command=sys.executable,  # Assumes venv Python
    args=[mcp_script_path],
)

# 3) Create the Portia instance
portia = Portia(config=config, tools=angel_registry)
print("✅ Portia initialized successfully with Angel One tools.")
print("Loaded tools:", [t.name for t in angel_registry.get_tools()])

# --- API Pydantic Models ---
class Intent(BaseModel):
    intent: str = Field(..., description="The user's primary goal. Must be one of: 'get_ltp', 'get_ohlc', 'get_portfolio', 'place_order', 'cancel_order', 'general_query'.")
    tradingsymbol: Optional[str] = Field(None, description="The stock symbol, if mentioned (e.g., 'RELIANCE-EQ').")
    order_id: Optional[str] = Field(None, description="The order ID for cancellation, if mentioned.")

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

def is_user_logged_in() -> bool:
    """Checks if the angel_session.json file exists."""
    return os.path.exists("angel_session.json")

# In api.py
# --- Reliable Plan Creation Functions ---
# The definitions for the 'create_..._plan' functions are here
def create_ltp_plan(tradingsymbol: str):
    """Builds a plan to get the LTP for a symbol."""
    builder = PlanBuilderV2("Fetch Last Traded Price")
    return (builder
        .invoke_tool_step(
            step_name="GetDetails",
            tool="mcp:angelone:get_symbol_details",
            args={"tradingsymbol": tradingsymbol}
        )
        .invoke_tool_step(
            step_name="GetLTP",
            tool="mcp:angelone:angel_get_ltp",
            
            args={"req": {
                "exchange": StepOutput("GetDetails")["exchange"],
                "tradingsymbol": StepOutput("GetDetails")["tradingsymbol"],
                "symboltoken": StepOutput("GetDetails")["symboltoken"],
            }}
        )
        .llm_step(
            task="Summarize the LTP data clearly for the user, including the symbol name and its last traded price.",
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

# Pre-built, reliable plan for placing an order
# In api.py, add this with your other plan functions

def create_order_execution_plan(order_params: dict):
    """Builds a robust, multi-step plan to execute a trade."""
    builder = PlanBuilderV2("Fetch Symbol Details and Place Order")
    return (builder
        # Step 1: Always get the latest symbol details first.
        .invoke_tool_step(
            step_name="GetDetails",
            tool="mcp:angelone:get_symbol_details",
            args={"tradingsymbol": order_params.get("tradingsymbol")}
        )
        # Step 2: Place the order using a combination of original params and details from Step 1.
        .invoke_tool_step(
            step_name="PlaceOrder",
            tool="mcp:angelone:angel_place_order",
            args={
                "order": StepOutput("GetDetails", lambda out: {
                    **order_params,  # Start with the params we already have
                    "symboltoken": out.get("symboltoken"), # Add/overwrite with fresh data
                    "exchange": out.get("exchange"),
                })
            }
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

# In api.py

# In api.py

# 1. Update the LoginRequest model to REMOVE totp
class LoginRequest(BaseModel):
    client_code: str
    password: str

# 2. Replace the entire login function with this automated version
@app.post("/login", response_model=ApiResponse, summary="Login to Angel One")
async def login(request: LoginRequest):
    """
    Logs the user into Angel One by automatically generating the TOTP.
    """
    print(f"Received login request for client code: {request.client_code}")

    try:
        # --- THIS IS THE NEW AUTOMATION PART ---
        totp_secret = os.getenv("ANGEL_TOTP_SECRET")
        if not totp_secret:
            raise ValueError("ANGEL_TOTP_SECRET not found in .env file.")

        # Generate the 6-digit code automatically
        totp_code = pyotp.TOTP(totp_secret).now()
        print(f"[DEBUG] Generated TOTP code: {totp_code}")
        # --- END OF AUTOMATION PART ---

        builder = PlanBuilderV2("Login to Angel One Broker")
        plan = (
            builder
            .invoke_tool_step(
                step_name="Login",
                tool="mcp:angelone:angel_login",
                args={
                    "client_code": request.client_code,
                    "password": request.password,
                    "totp": totp_code, # Use the generated code
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

    # --- ARCHITECTURAL NOTE FOR REVIEWERS ---
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
        # --- THIS IS THE FINAL, CORRECTED METHOD ---
        classification_builder = PlanBuilderV2("Classify User Intent")
        classification_plan = (classification_builder
            .llm_step(
                task=f"Classify the user's intent and extract entities from this query: '{request.message}'",
                output_schema=Intent
            )
            .final_output()
            .build()
        )
        plan_run = await portia.arun_plan(classification_plan)
        if plan_run.state == PlanRunState.FAILED:
            raise Exception(f"Could not understand intent. {plan_run.outputs.final_output.value}")
        intent_result = plan_run.outputs.final_output.value
        # --- END OF CORRECTION ---
        
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
            # Use the same reliable LLM-only plan technique for parsing order parameters
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
            return ApiResponse(content="I can't fetch historical chart data just yet, but this feature is coming soon!", type="text")
        else: # general_query
            return ApiResponse(content="I can currently fetch portfolios, check prices, and handle orders. Please try one of those actions.", type="text")

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
        
        order_plan = create_order_execution_plan(request.order_params)
        plan_run = await portia.arun_plan(order_plan)

        if plan_run.state == PlanRunState.FAILED:
             raise Exception(str(plan_run.outputs.final_output.value))
        
        summary = plan_run.outputs.final_output.value
        return ApiResponse(content=f"✅ Order execution plan completed!\n\n**Broker Summary:**\n{summary}")
        
    except Exception as e:
        print(f"Order execution failed: {e}")
        raise HTTPException(status_code=400, detail=f"Order execution failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # This allows running the API directly for testing
    uvicorn.run(app, host="0.0.0.0", port=8000)