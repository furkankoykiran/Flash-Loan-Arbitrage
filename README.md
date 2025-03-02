# Multi-DEX Flash Loan Arbitrage Bot

This bot monitors and executes flash loan arbitrage opportunities across multiple decentralized exchanges (DEXs) on Ethereum. Using advanced algorithms, it identifies profitable trading paths across the entire blockchain network and automatically executes trades when profit thresholds are met, while maintaining high security standards.

## Features

- Comprehensive DEX monitoring across multiple platforms including:
  - Uniswap V2 & V3
  - SushiSwap
  - PancakeSwap
  - Curve
  - Balancer
  - 1inch
  - Other emerging DEXs
- Dynamic DEX integration system for easy addition of new exchanges
- Smart contract security verification for each DEX interaction
- Real-time price monitoring and arbitrage path finding
- Advanced path optimization for maximum profits
- Automated token pair discovery and filtering
- Flash loan-powered arbitrage execution
- Multi-hop trade route optimization
- Configurable profit thresholds and gas optimization
- Telegram notifications for important events
- Automatic failover with multiple RPC endpoints
- Blacklist/whitelist token and DEX filtering
- Risk management system with automatic safety checks

## Project Structure

```
src/
├── __init__.py
├── arbitrage_bot.py    # Core arbitrage logic
├── config.py          # Configuration management
├── contracts.py       # Smart contract interactions
├── main.py           # Entry point
├── market_utils.py    # Market data utilities
├── notifications.py   # Telegram notifications
└── token_discovery.py # Token pair discovery
```

## Configuration

Copy `.env.example` to `.env` and configure the following:

### Required Settings

- `NETWORK_RPC_URL`: WebSocket RPC URL for Ethereum network
- `PRIVATE_KEY`: Your wallet's private key
- `WALLET_ADDRESS`: Your wallet's address

### Trading Settings

- `SLIPPAGE_TOLERANCE`: Maximum allowed slippage (in basis points)
- `MAX_GAS_PRICE`: Maximum gas price in gwei
- `MIN_PROFIT_THRESHOLD`: Minimum profit in ETH to execute trades
- `MAX_TRADE_HOPS`: Maximum number of trades in a single arbitrage path
- `SAFETY_THRESHOLD`: Minimum protocol TVL for security validation

### DEX Settings

- `ENABLED_DEXES`: List of DEXs to monitor
- `DEX_WEIGHTS`: Priority weights for different DEXs
- `NEW_DEX_DELAY`: Waiting period before trading on newly added DEXs

### Token Discovery Settings

- `MIN_LIQUIDITY_USD`: Minimum pool liquidity required
- `MIN_VOLUME_USD`: Minimum 24h trading volume required
- `TOKEN_BLACKLIST`: Tokens to ignore
- `TOKEN_WHITELIST`: Exclusive token list (if empty, monitors all except blacklist)
- `MIN_TOKEN_AGE`: Minimum age of token contracts (for security)
- `REQUIRED_AUDIT_SCORE`: Minimum security audit score for tokens

### Security Settings

- `MAX_EXPOSURE`: Maximum exposure per trade
- `SMART_CONTRACT_VERIFICATION`: Enable/disable automatic contract verification
- `SECURITY_ALERTS_THRESHOLD`: Threshold for security alert notifications

## Installation

### Prerequisites

1. Make sure Python 3.x is installed:
```bash
python3 --version
```

2. Install Poetry (dependency management tool):
   - For Unix-like systems (Linux, macOS):
     ```bash
     curl -sSL https://install.python-poetry.org | python3 -
     ```
   - For Windows:
     ```powershell
     (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
     ```

### Project Setup

1. Install project dependencies:
```bash
poetry install
```

2. Create and configure your environment file:
```bash
cp .env.example .env
# Edit .env with your settings
```

## Running the Bot

### Development Mode

```bash
# Activate poetry shell
poetry shell

# Run the bot
python3 src/main.py
```

### Production Mode

For production environments, it's recommended to use your system's service manager or process supervisor to run the bot. This ensures automatic restarts on failures and proper log management.

Popular options include:
- systemd (Linux)
- Supervisor
- PM2
- Docker

## Node Connection Options

### Public RPC Endpoints (No Storage Required)

Use these free public RPC endpoints in your .env file:

```
# Primary RPC
NETWORK_RPC_URL=wss://eth.public-rpc.com

# Backup RPCs
BACKUP_RPC_URLS=wss://ethereum.publicnode.com,wss://eth1.allthatnode.com,wss://1rpc.io/eth
```

Benefits:
- No disk space required
- No syncing needed
- Instant setup
- Multiple backup endpoints

## Security Considerations

- Never share or commit your private key
- Use a dedicated wallet for the bot
- Monitor gas prices to avoid excessive fees
- Test with small amounts first
- Keep your RPC endpoints private
- Verify smart contract addresses before trading
- Implement circuit breakers for unusual market conditions
- Regular security audits of trading paths
- Monitor protocol security scores
- Set maximum exposure limits per trade