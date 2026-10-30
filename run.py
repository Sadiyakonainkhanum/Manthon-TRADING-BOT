import sys
import codecs

# Ensure Windows terminal handles UTF-8 (e.g. Rupee sign ₹) safely
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import uvicorn
from engine.config import config


def main():
    print("=" * 76)
    print("    MANTHAN 2026 : AUTONOMOUS TRADING SYSTEMS CHALLENGE")
    print("    JNNCE CSE (Data Science) • 24-Hour National Hackathon")
    print("=" * 76)
    print(f"[*] Dashboard URL:         http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    print(f"[*] Server IP Configured:  {config.SERVER_IP or 'None (DEMO Sandbox Replay Active)'}")
    print(f"[*] Kafka Broker Target:   {config.kafka_broker or 'Waiting for SERVER_IP'}")
    print(f"[*] Order Gateway Target:  {config.rest_base_url or 'Waiting for SERVER_IP'}")
    print(f"[*] Consumer Group:        {config.consumer_group_id}")
    print(f"[*] Starting Capital:      ₹{config.STARTING_CAPITAL:,.2f}")
    print(f"[*] Rate Limit Pacing:     {config.MAX_ORDERS_PER_MINUTE} req/min (Max limit: 120)")
    print(f"[*] Mode:                  {'DEMO SIMULATION' if config.DEMO_MODE else 'LIVE HOST'}")
    print("=" * 76)
    print("[*] Press Ctrl+C in the terminal to halt.")
    print("=" * 76)

    uvicorn.run(
        "server.main:app",
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    main()
