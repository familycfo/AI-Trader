"""
Interactive Brokers Paper Trading Tool
MCP tool for executing trades on IB Paper Trading account
"""
from fastmcp import FastMCP
import sys
import os
from typing import Dict, List, Optional, Any
import fcntl
from pathlib import Path
from datetime import datetime
import json

# IB API imports
from ib_insync import IB, Stock, MarketOrder, util

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from tools.price_tools import get_yesterday_date, get_open_prices, get_latest_position
from tools.general_tools import get_config_value, write_config_value

mcp = FastMCP("IBPaperTradeTools")

# IB Connection settings - adjust these for your setup
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "7497"))  # 7497 for paper trading
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))


def _position_lock(signature: str):
    """Context manager for file-based lock to serialize position updates per signature."""
    class _Lock:
        def __init__(self, name: str):
            base_dir = Path(project_root) / "data" / "agent_data" / name
            base_dir.mkdir(parents=True, exist_ok=True)
            self.lock_path = base_dir / ".position.lock"
            self._fh = open(self.lock_path, "a+")
        
        def __enter__(self):
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            return self
        
        def __exit__(self, exc_type, exc, tb):
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
    
    return _Lock(signature)


def _connect_ib() -> IB:
    """
    Connect to Interactive Brokers TWS/Gateway
    
    Returns:
        IB: Connected IB instance
        
    Raises:
        ConnectionError: If unable to connect
    """
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        print(f"✅ Connected to IB Paper Trading at {IB_HOST}:{IB_PORT}")
        return ib
    except Exception as e:
        raise ConnectionError(f"❌ Failed to connect to IB: {e}")


def _get_ib_position(ib: IB, symbol: str) -> int:
    """
    Get current position from IB account
    
    Args:
        ib: Connected IB instance
        symbol: Stock symbol
        
    Returns:
        Current position quantity (positive for long, negative for short, 0 for none)
    """
    positions = ib.positions()
    for pos in positions:
        if hasattr(pos.contract, 'symbol') and pos.contract.symbol == symbol:
            return int(pos.position)
    return 0


def _execute_ib_order(ib: IB, symbol: str, quantity: int, action: str) -> Dict[str, Any]:
    """
    Execute order on IB Paper Trading account
    
    Args:
        ib: Connected IB instance
        symbol: Stock symbol
        quantity: Number of shares
        action: "BUY" or "SELL"
        
    Returns:
        Order execution details
    """
    try:
        # Create contract
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        
        # Create market order
        order = MarketOrder(action, quantity)
        
        # Place order
        trade = ib.placeOrder(contract, order)
        
        # Wait for order to fill (with timeout)
        ib.sleep(2)  # Give it 2 seconds to fill
        
        # Check order status
        if trade.orderStatus.status in ['Filled', 'PreSubmitted', 'Submitted']:
            fill_price = trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice > 0 else 0
            
            return {
                "success": True,
                "order_id": trade.order.orderId,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "status": trade.orderStatus.status,
                "fill_price": fill_price,
                "commission": trade.orderStatus.commission
            }
        else:
            return {
                "success": False,
                "error": f"Order not filled. Status: {trade.orderStatus.status}",
                "order_id": trade.order.orderId
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
def buy(symbol: str, amount: int) -> Dict[str, Any]:
    """
    Buy stock on IB Paper Trading account
    
    This function executes a real buy order on Interactive Brokers Paper Trading,
    then updates the local position records.
    
    Args:
        symbol: Stock symbol (e.g., "AAPL", "MSFT")
        amount: Number of shares to buy (must be positive integer)
        
    Returns:
        Dict containing execution result and updated positions
    """
    # Get environment variables
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")
    
    today_date = get_config_value("TODAY_DATE")
    
    # Validate amount
    if amount <= 0:
        return {"error": "Amount must be positive", "symbol": symbol, "date": today_date}
    
    # Connect to IB
    try:
        ib = _connect_ib()
    except ConnectionError as e:
        return {"error": str(e), "symbol": symbol, "date": today_date}
    
    try:
        # Get current position (both local and IB)
        with _position_lock(signature):
            current_position, current_action_id = get_latest_position(today_date, signature)
        
        # Get stock price for recording
        try:
            this_symbol_price = get_open_prices(today_date, [symbol])[f'{symbol}_price']
        except KeyError:
            ib.disconnect()
            return {"error": f"Symbol {symbol} not found in price data", "symbol": symbol, "date": today_date}
        
        # Check cash availability (estimated)
        required_cash = this_symbol_price * amount
        if current_position.get("CASH", 0) < required_cash:
            ib.disconnect()
            return {
                "error": "Insufficient cash (local record)", 
                "required_cash": required_cash,
                "cash_available": current_position.get("CASH", 0),
                "symbol": symbol,
                "date": today_date
            }
        
        # Execute order on IB
        execution_result = _execute_ib_order(ib, symbol, amount, "BUY")
        
        if not execution_result.get("success"):
            ib.disconnect()
            return {
                "error": f"IB order failed: {execution_result.get('error')}",
                "symbol": symbol,
                "date": today_date,
                "execution_details": execution_result
            }
        
        # Update local position records
        new_position = current_position.copy()
        
        # Use actual fill price if available, otherwise use estimated price
        actual_price = execution_result.get("fill_price", this_symbol_price)
        actual_cost = actual_price * amount
        
        new_position["CASH"] = new_position.get("CASH", 0) - actual_cost
        new_position[symbol] = new_position.get(symbol, 0) + amount
        
        # Save to position file
        position_file_path = os.path.join(project_root, "data", "agent_data", signature, "position", "position.jsonl")
        
        with _position_lock(signature):
            with open(position_file_path, "a") as f:
                record = {
                    "date": today_date,
                    "id": current_action_id + 1,
                    "this_action": {
                        "action": "buy",
                        "symbol": symbol,
                        "amount": amount,
                        "ib_order_id": execution_result.get("order_id"),
                        "fill_price": actual_price,
                        "commission": execution_result.get("commission", 0)
                    },
                    "positions": new_position,
                    "ib_execution": execution_result
                }
                print(f"Writing to position.jsonl: {json.dumps(record)}")
                f.write(json.dumps(record) + "\n")
        
        # Mark that trading occurred
        write_config_value("IF_TRADE", True)
        
        # Disconnect IB
        ib.disconnect()
        
        # Return updated position with execution details
        return {
            **new_position,
            "execution_details": execution_result,
            "actual_price": actual_price
        }
        
    except Exception as e:
        ib.disconnect()
        return {
            "error": f"Unexpected error: {str(e)}",
            "symbol": symbol,
            "date": today_date
        }


@mcp.tool()
def sell(symbol: str, amount: int) -> Dict[str, Any]:
    """
    Sell stock on IB Paper Trading account
    
    This function executes a real sell order on Interactive Brokers Paper Trading,
    then updates the local position records.
    
    Args:
        symbol: Stock symbol (e.g., "AAPL", "MSFT")
        amount: Number of shares to sell (must be positive integer)
        
    Returns:
        Dict containing execution result and updated positions
    """
    # Get environment variables
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")
    
    today_date = get_config_value("TODAY_DATE")
    
    # Validate amount
    if amount <= 0:
        return {"error": "Amount must be positive", "symbol": symbol, "date": today_date}
    
    # Connect to IB
    try:
        ib = _connect_ib()
    except ConnectionError as e:
        return {"error": str(e), "symbol": symbol, "date": today_date}
    
    try:
        # Get current position (both local and IB)
        with _position_lock(signature):
            current_position, current_action_id = get_latest_position(today_date, signature)
        
        # Verify we have the position locally
        if symbol not in current_position:
            ib.disconnect()
            return {"error": f"No position for {symbol}", "symbol": symbol, "date": today_date}
        
        if current_position[symbol] < amount:
            ib.disconnect()
            return {
                "error": "Insufficient shares (local record)",
                "have": current_position.get(symbol, 0),
                "want_to_sell": amount,
                "symbol": symbol,
                "date": today_date
            }
        
        # Get stock price for recording
        try:
            this_symbol_price = get_open_prices(today_date, [symbol])[f'{symbol}_price']
        except KeyError:
            ib.disconnect()
            return {"error": f"Symbol {symbol} not found in price data", "symbol": symbol, "date": today_date}
        
        # Verify IB position matches (optional safety check)
        ib_position = _get_ib_position(ib, symbol)
        if ib_position < amount:
            ib.disconnect()
            return {
                "error": "Insufficient shares in IB account",
                "ib_position": ib_position,
                "want_to_sell": amount,
                "symbol": symbol,
                "date": today_date
            }
        
        # Execute order on IB
        execution_result = _execute_ib_order(ib, symbol, amount, "SELL")
        
        if not execution_result.get("success"):
            ib.disconnect()
            return {
                "error": f"IB order failed: {execution_result.get('error')}",
                "symbol": symbol,
                "date": today_date,
                "execution_details": execution_result
            }
        
        # Update local position records
        new_position = current_position.copy()
        
        # Use actual fill price if available, otherwise use estimated price
        actual_price = execution_result.get("fill_price", this_symbol_price)
        actual_proceeds = actual_price * amount
        
        new_position[symbol] = new_position.get(symbol, 0) - amount
        new_position["CASH"] = new_position.get("CASH", 0) + actual_proceeds
        
        # Save to position file
        position_file_path = os.path.join(project_root, "data", "agent_data", signature, "position", "position.jsonl")
        
        with _position_lock(signature):
            with open(position_file_path, "a") as f:
                record = {
                    "date": today_date,
                    "id": current_action_id + 1,
                    "this_action": {
                        "action": "sell",
                        "symbol": symbol,
                        "amount": amount,
                        "ib_order_id": execution_result.get("order_id"),
                        "fill_price": actual_price,
                        "commission": execution_result.get("commission", 0)
                    },
                    "positions": new_position,
                    "ib_execution": execution_result
                }
                print(f"Writing to position.jsonl: {json.dumps(record)}")
                f.write(json.dumps(record) + "\n")
        
        # Mark that trading occurred
        write_config_value("IF_TRADE", True)
        
        # Disconnect IB
        ib.disconnect()
        
        # Return updated position with execution details
        return {
            **new_position,
            "execution_details": execution_result,
            "actual_price": actual_price
        }
        
    except Exception as e:
        ib.disconnect()
        return {
            "error": f"Unexpected error: {str(e)}",
            "symbol": symbol,
            "date": today_date
        }


@mcp.tool()
def get_ib_account_summary() -> Dict[str, Any]:
    """
    Get IB Paper Trading account summary
    
    Returns account balance, buying power, and current positions from IB.
    Useful for verifying account status before trading.
    
    Returns:
        Dict containing account summary information
    """
    try:
        ib = _connect_ib()
        
        # Get account values
        account_values = ib.accountValues()
        account_summary = {}
        
        for value in account_values:
            if value.tag in ['NetLiquidation', 'CashBalance', 'BuyingPower', 'GrossPositionValue']:
                account_summary[value.tag] = float(value.value)
        
        # Get positions
        positions = ib.positions()
        position_summary = []
        
        for pos in positions:
            if hasattr(pos.contract, 'symbol'):
                position_summary.append({
                    "symbol": pos.contract.symbol,
                    "position": int(pos.position),
                    "market_price": float(pos.marketPrice) if pos.marketPrice else 0,
                    "market_value": float(pos.marketValue) if pos.marketValue else 0,
                    "avg_cost": float(pos.avgCost) if pos.avgCost else 0
                })
        
        ib.disconnect()
        
        return {
            "success": True,
            "account_summary": account_summary,
            "positions": position_summary,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    port = int(os.getenv("TRADE_HTTP_PORT", "8002"))
    print(f"🚀 Starting IB Paper Trading MCP Server on port {port}")
    print(f"📡 IB Connection: {IB_HOST}:{IB_PORT} (Client ID: {IB_CLIENT_ID})")
    mcp.run(transport="streamable-http", port=port)
