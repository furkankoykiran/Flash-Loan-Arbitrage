# Flash Loan Arbitrage Bot

This bot monitors and executes flash loan arbitrage opportunities between Uniswap V2 and SushiSwap on Ethereum. It automatically identifies profitable trading paths and executes trades when the profit threshold is met.

## Features

- Real-time price monitoring across Uniswap V2 and SushiSwap
- Automatic token pair discovery and filtering
- Flash loan-powered arbitrage execution
- Configurable profit thresholds and gas optimization
- Telegram notifications for important events
- Automatic failover with multiple RPC endpoints
- Blacklist/whitelist token filtering

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

### Token Discovery Settings

- `MIN_LIQUIDITY_USD`: Minimum pool liquidity required
- `MIN_VOLUME_USD`: Minimum 24h trading volume required
- `TOKEN_BLACKLIST`: Tokens to ignore
- `TOKEN_WHITELIST`: Exclusive token list (if empty, monitors all except blacklist)

## Running as a System Service

### Prerequisites

1. Make sure Python 3.x is installed:
```bash
python3 --version
```

2. Install poetry if not already installed:
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### Option 1: Automated Installation

The easiest way to install the service is using the installation script:

```bash
# Make the script executable
chmod +x install-service.sh

# Run the installation script
sudo ./install-service.sh
```

This will automatically:
- Install poetry if not present
- Install project dependencies
- Create necessary log files
- Set correct permissions
- Install and enable the service
- Start the bot immediately
- Configure autostart on boot

### Option 2: Manual Installation

If you prefer to set up the service manually:

1. Install dependencies:
```bash
poetry install
```

2. Copy the service file to systemd directory:
```bash
sudo cp flash-loan-bot.service /etc/systemd/system/
```

3. Create log files and set permissions:
```bash
sudo touch /var/log/flash-loan-bot.log
sudo touch /var/log/flash-loan-bot.error.log
sudo chown $USER:$USER /var/log/flash-loan-bot.log
sudo chown $USER:$USER /var/log/flash-loan-bot.error.log
```

4. Reload systemd daemon:
```bash
sudo systemctl daemon-reload
```

5. Enable and start the service:
```bash
sudo systemctl enable flash-loan-bot
sudo systemctl start flash-loan-bot
```

## Service Management Commands

```bash
# Check status
sudo systemctl status flash-loan-bot

# View logs
tail -f /var/log/flash-loan-bot.log
tail -f /var/log/flash-loan-bot.error.log

# Stop the service
sudo systemctl stop flash-loan-bot

# Restart the service
sudo systemctl restart flash-loan-bot

# Disable autostart
sudo systemctl disable flash-loan-bot
```

## Running Manually (Development)

To run the bot manually for development:

```bash
# Activate poetry shell
poetry shell

# Run the bot
python3 src/main.py
```

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