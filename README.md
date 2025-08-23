# 🧠 Portia Trading Agent

Welcome to the Portia Trading Agent, a conversational AI application for interacting with your Angel One trading account. This agent uses Google's Gemini models via the Portia AI framework to understand natural language commands, fetch market data, analyze your portfolio, and securely place trades.

The user interface is built with Streamlit, providing a clean, modern chat experience.



---

## ✨ Features

* **Conversational Interface:** Interact with your trading account using plain English.
* **Secure Login:** A dedicated, secure login flow for your Angel One account.
* **Real-time Data:** Fetch last-traded prices (LTP) and historical OHLC data.
* **Portfolio Analysis:** View and analyze your current holdings and positions.
* **Safe Order Placement:** A hybrid system that uses AI to understand your trade request and requires explicit user confirmation in the UI before executing any order.
* **Flexible & Reliable:** Uses a hybrid agent design.
    * **Reliable Plans (`PlanBuilderV2`):** For critical, sequential tasks like login and order execution.
    * **Autonomous LLM:** For flexible, open-ended analysis and queries.

---

## 🛠️ Tech Stack

* **AI Framework:** [Portia AI](https://www.portia.ai/)
* **LLM:** Google Gemini 1.5 Flash
* **Backend:** FastAPI
* **Frontend:** Streamlit
* **Broker API:** Angel One SmartAPI

---

## 🚀 Getting Started

### Prerequisites

* Python 3.8+
* An Angel One trading account with SmartAPI access.
* A Google AI Studio API key for Gemini.

### 1. Clone the Repository

```bash
git clone <https://github.com/SAIVARDHAN15/PortiaTradingCopilot.git>
cd PortiaAgent
