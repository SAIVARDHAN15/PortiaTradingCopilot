# 📈 AI-Powered Trading Agent with Portia + AngelOne  

An intelligent trading companion that connects **Portia AI** with **AngelOne APIs** to help users analyze markets, understand their portfolio, and place trades confidently — all through a natural chat interface with a modern, streamlined UI.  

---

## 🚀 Overview  

Retail investors face two main challenges:  
1. **Overwhelming information** – too much raw data, not enough insights.  
2. **Complex execution** – navigating brokers’ APIs & tools is intimidating.  

Our solution bridges this gap:  
- **Conversational AI assistant** powered by Portia.  
- **Integrated with AngelOne** for real order execution.  
- **Built-in market scraping & portfolio analytics** to help users make better trading decisions.  
- **Modern UI (Streamlit)** that makes interaction simple, intuitive, and beautiful.  

---

## ✨ Key Features  

### 🧠 Smart Intent Classification  
- User requests are **understood via LLM-driven intent parsing**.  
- Supports intents like `place_order`, `get_stock_info`, `analyze_portfolio`, `market_movers`.  
- Reliable plan-based execution ensures the right tools are invoked every time.  

### 📊 Stock & Portfolio Analysis  
- Fetches **real-time OHLC data** via AngelOne.  
- AI generates **insightful, human-like stock analysis**.  
- Portfolio analysis **loops through holdings**, provides stock-level insights, then summarizes strengths & risks.  

### 💸 Trade Execution (with Confirmation Flow)  
- Users can **place trades naturally in chat** (e.g., “Buy 1 share of Suzlon”).  
- Order parameters auto-parsed with schema validation.  
- **Confirmation step with buttons** ensures safety before execution.  
- Trades routed securely via AngelOne API.  

### 🌐 Market Movers Scraper  
- Pulls **top gainers/losers** from NSE dynamically.  
- Keeps users updated on opportunities without leaving chat.  

### 🎨 Streamlined User Interface  
- Built with **Streamlit** for simplicity and elegance.  
- Chat-first interface with **structured confirmations, buttons, and clean layout**.  
- Focused on **UX and clarity** — no clutter, just actionable insights.  

---

## 🏆 Why This Project Stands Out  

### 🔹 Potential Impact  
Empowers retail investors by making **data-driven, AI-assisted trading accessible**. Removes friction in research, analysis, and execution just by general language.  

### 🔹 Creativity & Originality  
- Innovative blend of **Portia’s agent planning** with a **real brokerage API**.  
- Creative use of **LLM + structured schemas + plans** to ensure reliability.  
- Combines **NSE scraping, broker integration, portfolio insights, and execution** in one unified assistant.  

### 🔹 Learning & Growth  
- Team tackled **new domains simultaneously**: Portia AI, AngelOne APIs, database indexing, and frontend UX.  
- Solved real-world challenges (e.g., symbol lookup via SQLite, robust error handling, safe trade confirmation).  
- First time building a **full-stack AI trading agent**.  

### 🔹 Implementation of the Idea  
- Fully functional **end-to-end pipeline**:  
  - Chat → Intent → Plan → MCP tool → Broker API → Confirmation → Execution.  
- Resilient error handling and structured outputs.  
- Clear separation of backend (`api.py`, `angelone_mcp_server.py`) and UI (`ui.py`).  

### 🔹 Aesthetics & UX  
- Streamlined chat experience.  
- Confirmation buttons for safe order flow.  
- Minimal, elegant design with clear status updates.  
- Judges can interact like a **real user** without needing to understand backend complexity.  

---

## 🛠️ Tech Stack  

- **[Portia](https://github.com/portia)** – AI planning and orchestration  
- **AngelOne SmartAPI** – real trading integration  
- **SQLite** – local instrument database for symbol lookups  
- **Streamlit** – modern chat-based UI  
- **Python (FastAPI + Pydantic)** – backend and API design  
- **BeautifulSoup + Requests** – market mover web scraping  

---

## ⚙️ How It Works  

1. **Login** with AngelOne credentials → session saved securely. 
2. **Chat naturally** with the assistant (e.g., *“What’s happening with RELIANCE today?”*).  
3. **Portia classifies intent** and builds a **robust multi-step plan**.  
4. MCP tools query AngelOne / scrape NSE / run analysis.  
5. Assistant **summarizes insights** or prepares an **order for confirmation**.  
6. On confirmation, order is **executed via AngelOne API**.  

---

## How To Run
1. Install the requirements
2. Run api.py Backend
3. Run ui.py Frontend 

## 🏁 Conclusion  

This project delivers a **powerful, creative, and user-friendly AI trading assistant** that demonstrates the potential of **Portia in financial automation**.  

By combining **LLM intelligence**, **structured planning**, **real brokerage integration**, and a **beautiful UI**, it empowers retail investors to make informed decisions and act on them seamlessly.  

> 🚀 More than just a demo — it’s a glimpse into the **future of AI-driven trading.**  

---
