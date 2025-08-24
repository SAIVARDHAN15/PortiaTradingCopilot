# ui.py
import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime

# --- Page Configuration ---
st.set_page_config(
    page_title="Portia Trading Agent",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- API Configuration ---
API_BASE_URL = "http://127.0.0.1:8000"

if "messages" not in st.session_state:
    st.session_state.messages = []
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = None


# --- UI Components ---

def render_sidebar():
    """Renders the sidebar with the simplified login form."""
    with st.sidebar:
        # --- Portia Branding ---
        st.markdown(
            """
            <div style="text-align: center;">
                <h1 style="font-weight: 600;">🧠 Portia</h1>
                <h3 style="font-weight: 300;">Your Personal Trading Agent</h3>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown("---")

        # --- Login and Status ---
        if st.session_state.logged_in:
            st.success("Status: Connected ✅")
            st.info("You are logged in. You can start sending messages in the chat window.")
        else:
            st.warning("Status: Disconnected 🔴")
            with st.form("login_form"):
                st.subheader("Angel One Login")
                client_code = st.text_input("Client Code", key="client_code")
                password = st.text_input("Password", type="password", key="password")
                # The TOTP field is now removed
                submitted = st.form_submit_button("Login")

                if submitted:
                    # We pass the new handle_login function without totp
                    handle_login(client_code, password)
        
        st.markdown("---")
        st.markdown(
            "<p style='text-align: center; color: grey;'>Powered by Portia AI</p>",
            unsafe_allow_html=True
        )


def render_chat_history():
    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message.get("content"): st.markdown(message["content"])
            if message.get("type") == "json": st.json(message["data"])
            if message.get("type") == "dataframe":
                try: st.dataframe(pd.DataFrame(message["data"]))
                except Exception as e: st.error(f"Failed to render dataframe: {e}")
            
            # This is the updated confirmation logic
            if message.get("type") == "confirmation":
                if i == len(st.session_state.messages) - 1 and st.session_state.pending_confirmation:
                    col1, col2, col3 = st.columns([1, 1, 2])
                    with col1:
                        if st.button("✅ Confirm", use_container_width=True, key=f"confirm_{i}"):
                            handle_order_confirmation()
                            st.rerun()
                    with col2:
                        if st.button("❌ Cancel", use_container_width=True, key=f"cancel_{i}"):
                            st.session_state.pending_confirmation = None
                            st.session_state.messages.append({
                                "role": "assistant", "content": "Order cancelled.",
                                "type": "text", "data": None
                            })
                            st.rerun()


# --- API Call Handlers ---

def handle_login(client_code, password): # Remove totp from arguments
    """Sends login credentials to the backend API."""
    with st.spinner("Logging in..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/login",
                # The request body no longer contains totp
                json={"client_code": client_code, "password": password}
            )
            response.raise_for_status()
            
            api_response = response.json()
            st.session_state.logged_in = True
            st.session_state.messages.append({
                "role": "assistant",
                "content": api_response["content"],
                "type": "text",
                "data": None
            })
            st.rerun()
        except requests.exceptions.RequestException as e:
            error_detail = e.response.json().get("detail", str(e)) if e.response else str(e)
            st.error(f"Login failed: {error_detail}")


def handle_chat_message(prompt: str):
    """Sends a user's chat message to the backend and handles the response."""
    with st.spinner("Portia is thinking..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/chat",
                json={"message": prompt}
            )
            response.raise_for_status()

            api_response = response.json()

            # Always add assistant message to history
            st.session_state.messages.append({
                "role": "assistant",
                "content": api_response.get("content"),
                "type": api_response.get("type"),
                "data": api_response.get("data")
            })

            # If it's a pending order confirmation, store the params
            if api_response.get("status") == "pending_confirmation":
                st.session_state.pending_confirmation = api_response.get("data")

        except requests.exceptions.RequestException as e:
            error_detail = e.response.json().get("detail", str(e)) if e.response else str(e)
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Error: {error_detail}",
                "type": "error",
                "data": None
            })


def handle_order_confirmation():
    """Sends the confirmed order details to the backend for execution."""
    if st.session_state.pending_confirmation:
        # Show a spinner WHILE the order is being placed
        with st.spinner("Placing order..."):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/execute_order",
                    json={"order_params": st.session_state.pending_confirmation}
                )
                response.raise_for_status()
                api_response = response.json()
                # Add the success message to the chat
                st.session_state.messages.append({
                    "role": "assistant", "content": api_response.get("content"),
                    "type": "text", "data": None
                })
            except requests.exceptions.RequestException as e:
                error_detail = e.response.json().get("detail", str(e)) if e.response else str(e)
                st.session_state.messages.append({
                    "role": "assistant", "content": f"Order Placement Failed: {error_detail}",
                    "type": "error", "data": None
                })
            finally:
                # Clear the pending state AFTER the attempt
                st.session_state.pending_confirmation = None


# --- Main Application Logic ---

render_sidebar()

st.title("Portia Trading Agent Chat")
st.caption("A conversational agent for market analysis and trading.")

# Display initial welcome message if chat is empty
if not st.session_state.messages:
    st.session_state.messages.append({
        "role": "assistant",
        "content": "Welcome! Please log in using the sidebar to begin. Once logged in, you can ask me to check prices, review your portfolio, or place trades.",
        "type": "text",
        "data": None
    })

render_chat_history()

# Get user input
if prompt := st.chat_input("Ask me anything about your portfolio..."):
    # Add user message to state and display it
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Process the message and get assistant's response
    handle_chat_message(prompt)
    
    # Rerun to display the new assistant message
    st.rerun()