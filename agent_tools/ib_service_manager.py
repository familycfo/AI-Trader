#!/usr/bin/env python3
"""
MCP Service Startup Script - IB Paper Trading Version
Supports switching between IB Paper Trading and original simulation mode
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Import base service manager
from start_mcp_services import MCPServiceManager


class IBMCPServiceManager(MCPServiceManager):
    """
    Enhanced MCP Service Manager with IB Paper Trading support
    
    Inherits from base MCPServiceManager and adds ability to switch
    between IB Paper Trading and original simulation mode via environment variable.
    """
    
    def __init__(self):
        super().__init__()
        
        # Check if IB mode is enabled via environment variable
        use_ib = os.getenv("USE_IB_PAPER", "false").lower() == "true"
        
        if use_ib:
            # Replace trade service with IB Paper Trading version
            self.service_configs['trade'] = {
                'script': 'tool_trade_ib_paper.py',
                'name': 'IBPaperTradeTools',
                'port': self.ports['trade']
            }
            
            # Display IB connection info
            ib_host = os.getenv("IB_HOST", "127.0.0.1")
            ib_port = os.getenv("IB_PORT", "7497")
            ib_client_id = os.getenv("IB_CLIENT_ID", "1")
            
            print("=" * 60)
            print("🔧 MODE: IB Paper Trading")
            print("=" * 60)
            print(f"📡 IB Connection:")
            print(f"   Host: {ib_host}")
            print(f"   Port: {ib_port} ({'Paper Trading' if ib_port == '7497' else 'Live Trading'})")
            print(f"   Client ID: {ib_client_id}")
            print("=" * 60)
            
            # Verify IB connection requirements
            self._check_ib_requirements()
        else:
            # Use original simulation mode
            print("=" * 60)
            print("🔧 MODE: Original Simulation (No real trading)")
            print("=" * 60)
    
    def _check_ib_requirements(self):
        """Check if IB connection requirements are met"""
        try:
            import ib_insync
            print("✅ ib_insync package installed")
        except ImportError:
            print("❌ ERROR: ib_insync not installed")
            print("   Install with: pip install ib_insync")
            sys.exit(1)
        
        # Check if IB Gateway/TWS might be running (basic port check)
        ib_host = os.getenv("IB_HOST", "127.0.0.1")
        ib_port = int(os.getenv("IB_PORT", "7497"))
        
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((ib_host, ib_port))
            sock.close()
            
            if result == 0:
                print(f"✅ IB Gateway/TWS detected on {ib_host}:{ib_port}")
            else:
                print(f"⚠️  WARNING: No service detected on {ib_host}:{ib_port}")
                print("   Please start IB Gateway or TWS before trading")
                print("   Services will start anyway, but trading will fail without IB")
        except Exception as e:
            print(f"⚠️  Could not check IB connection: {e}")
    
    def start_all_services(self):
        """Start all services with enhanced logging for IB mode"""
        use_ib = os.getenv("USE_IB_PAPER", "false").lower() == "true"
        
        if use_ib:
            print("\n⚠️  IMPORTANT REMINDERS:")
            print("   1. Ensure IB Gateway/TWS is running")
            print("   2. Paper Trading account should be logged in")
            print("   3. API connection should be enabled in IB settings")
            print("   4. Port 7497 should be accessible")
            print()
        
        # Call parent start method
        super().start_all_services()
    
    def print_service_info(self):
        """Print service information with IB mode indicator"""
        super().print_service_info()
        
        use_ib = os.getenv("USE_IB_PAPER", "false").lower() == "true"
        if use_ib:
            print("\n" + "=" * 60)
            print("🔴 LIVE IB PAPER TRADING MODE ACTIVE")
            print("=" * 60)
            print("All trades will be executed on Interactive Brokers Paper Account")
            print("Monitor your IB account for real-time updates")
            print("=" * 60)


def main():
    """Main function with usage instructions"""
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'status':
            # Status check mode
            manager = IBMCPServiceManager()
            manager.status()
            return
        elif sys.argv[1] in ['-h', '--help']:
            print_usage()
            return
    
    # Startup mode
    print_banner()
    manager = IBMCPServiceManager()
    manager.start_all_services()


def print_banner():
    """Print startup banner"""
    print(r"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║           AI-Trader MCP Services Manager                  ║
    ║                with IB Paper Trading                      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)


def print_usage():
    """Print usage instructions"""
    print("""
Usage: python start_mcp_services_ib.py [option]

Options:
    (none)      Start all MCP services
    status      Check service status
    -h, --help  Show this help message

Environment Variables:
    USE_IB_PAPER      true/false - Enable IB Paper Trading mode (default: false)
    IB_HOST           IB Gateway host (default: 127.0.0.1)
    IB_PORT           IB Gateway port (default: 7497 for paper, 7496 for live)
    IB_CLIENT_ID      Unique client ID (default: 1)
    
    MATH_HTTP_PORT    Math service port (default: 8000)
    SEARCH_HTTP_PORT  Search service port (default: 8001)
    TRADE_HTTP_PORT   Trade service port (default: 8002)
    GETPRICE_HTTP_PORT Price service port (default: 8003)

Examples:

    # Start with original simulation mode
    python start_mcp_services_ib.py
    
    # Start with IB Paper Trading mode
    export USE_IB_PAPER=true
    python start_mcp_services_ib.py
    
    # Check service status
    python start_mcp_services_ib.py status
    
    # Quick test with IB
    USE_IB_PAPER=true python start_mcp_services_ib.py

Notes:
    - Original mode: All trades are simulated locally
    - IB mode: All trades are executed on IB Paper Trading account
    - Switch modes anytime by changing USE_IB_PAPER environment variable
    - No code changes needed to switch between modes
    """)


if __name__ == "__main__":
    main()
