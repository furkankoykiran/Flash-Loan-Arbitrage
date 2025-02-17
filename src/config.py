import os
import logging
from typing import Dict, Optional
from decimal import Decimal
from dotenv import load_dotenv
from web3 import Web3
from web3.providers.websocket import WebsocketProvider
from web3.middleware import geth_poa_middleware
import json
import time
import asyncio

from .notifications import TelegramNotifier
from .market_utils import MarketUtils

logger = logging.getLogger(__name__)

class Config:
    def __init__(self):
        load_dotenv()
        
        # Network configuration
        self.rpc_url = os.getenv('NETWORK_RPC_URL')
        self.backup_urls = os.getenv('BACKUP_RPC_URLS', '').split(',') if os.getenv('BACKUP_RPC_URLS') else []
        self.chain_id = int(os.getenv('CHAIN_ID', '1'))
        self.current_rpc_index = 0
        self.available_rpcs = [self.rpc_url] + [url for url in self.backup_urls if url.strip()]
        
        # Initialize Web3 with WebSocket provider
        self.w3 = self._initialize_web3()
        if not self.w3:
            self._try_backup_rpcs()
        
        # Wallet configuration
        self.private_key = os.getenv('PRIVATE_KEY')
        self.wallet_address = os.getenv('WALLET_ADDRESS')
        
        if self.private_key and self.wallet_address:
            logger.info(f"Wallet configured: {self.wallet_address}")
        
        # Contract addresses
        self.uniswap_router = os.getenv('UNISWAP_ROUTER_ADDRESS')
        self.sushiswap_router = os.getenv('SUSHISWAP_ROUTER_ADDRESS')
        
        # Trading parameters
        self.slippage_tolerance = int(os.getenv('SLIPPAGE_TOLERANCE', '50'))
        self.max_gas_price = int(os.getenv('MAX_GAS_PRICE', '100'))
        self.min_profit_threshold = Decimal(os.getenv('MIN_PROFIT_THRESHOLD', '0.00005'))
        
        # Token configuration
        self.token_addresses = {}
        self.token_ids = {}
        self.min_liquidity = float(os.getenv('MIN_LIQUIDITY_USD', '100000'))  # Minimum liquidity in USD
        self.min_volume = float(os.getenv('MIN_VOLUME_USD', '50000'))  # Minimum 24h volume in USD
        self.token_blacklist = set(os.getenv('TOKEN_BLACKLIST', '').split(','))
        self.token_whitelist = set(os.getenv('TOKEN_WHITELIST', '').split(','))
        
        # Initialize token discovery
        if self.w3 and self.w3.is_connected():
            from .token_discovery import TokenDiscovery
            self.token_discovery = TokenDiscovery(self.w3)
            self.token_discovery.min_liquidity_usd = self.min_liquidity
            self.token_discovery.min_volume_usd = self.min_volume
        else:
            self.token_discovery = None
        
        # Initialize market utils
        if self.w3 and self.w3.is_connected():
            self.market_utils = MarketUtils(self.w3)
            logger.info("Market utils initialized")
        else:
            self.market_utils = None
            logger.error("Failed to initialize market utils - no Web3 connection")
        
        # Telegram configuration
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_channel = os.getenv('TELEGRAM_CHANNEL_ID')
        
        # Initialize Telegram notifier
        if self.telegram_token and self.telegram_channel:
            self.notifier = TelegramNotifier(self.telegram_token, self.telegram_channel)
            logger.info("Telegram notifications enabled")
        else:
            self.notifier = None
            logger.info("Telegram notifications disabled (missing configuration)")
            
        # Bot statistics
        self.stats = {
            'opportunities_found': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_profit_eth': Decimal('0'),
            'total_profit_usd': Decimal('0')
        }

    def _initialize_web3(self) -> Optional[Web3]:
        """Initialize Web3 with WebSocket provider"""
        try:
            if not self.rpc_url:
                raise ValueError("NETWORK_RPC_URL not found in .env")
            
            if not self.rpc_url.startswith(('ws://', 'wss://')):
                raise ValueError("NETWORK_RPC_URL must be a WebSocket URL starting with ws:// or wss://")
            
            # Configure WebSocket provider
            provider_kwargs = {
                'websocket_timeout': 60,
                'websocket_kwargs': {
                    'ping_interval': 30,
                    'ping_timeout': 10,
                    'max_size': 2**22,
                }
            }
            
            provider = WebsocketProvider(self.rpc_url, **provider_kwargs)
            w3 = Web3(provider)
            
            # Add middleware
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            
            # Test connection with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if w3.is_connected() and w3.eth.chain_id == self.chain_id:
                        logger.info(f"Connected to Ethereum network (Chain ID: {self.chain_id})")
                        return w3
                except Exception:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    raise
            
            raise ConnectionError("Failed to establish connection after multiple attempts")
            
        except Exception as e:
            logger.error(f"Web3 initialization failed for {self.rpc_url}: {str(e)}")
            return None
            
    def _try_backup_rpcs(self) -> Optional[Web3]:
        """Try connecting to backup RPC endpoints"""
        if not self.backup_urls:
            return None
            
        for i, url in enumerate(self.backup_urls):
            if not url.strip():
                continue
                
            try:
                self.rpc_url = url
                self.current_rpc_index = i + 1
                logger.info(f"Attempting connection to backup RPC: {url}")
                w3 = self._initialize_web3()
                if w3 and w3.is_connected():
                    logger.info(f"Successfully connected to backup RPC: {url}")
                    self.w3 = w3
                    return w3
            except Exception as e:
                logger.error(f"Failed to connect to backup RPC {url}: {str(e)}")
                continue
        
        return None
        
    def _reconnect(self) -> bool:
        """Attempt to reconnect using current or backup RPCs"""
        if self.w3 and self.w3.is_connected():
            return True
            
        logger.info("Connection lost, attempting to reconnect...")
        
        # Try current RPC first
        self.w3 = self._initialize_web3()
        if self.w3 and self.w3.is_connected():
            return True
            
        # Try backup RPCs
        self.w3 = self._try_backup_rpcs()
        return bool(self.w3 and self.w3.is_connected())
        
    def validate_config(self) -> bool:
        """Validate that all required configuration is present"""
        if not self.w3 or not self.w3.is_connected():
            return False
            
        required_fields = [
            self.private_key,
            self.wallet_address,
            self.uniswap_router,
            self.sushiswap_router
        ]
        
        missing_fields = [i for i, field in enumerate(required_fields) if not field]
        if missing_fields:
            logger.error(f"Missing required configuration fields at indices: {missing_fields}")
            return False
            
        # Check wallet address format
        try:
            if not self.w3.is_address(self.wallet_address):
                logger.error(f"Invalid wallet address format: {self.wallet_address}")
                return False
            
            # Verify wallet has balance
            balance = self.w3.eth.get_balance(self.wallet_address)
            eth_balance = float(self.w3.from_wei(balance, 'ether'))
            logger.info(f"Wallet balance: {eth_balance:.6f} ETH")
            
        except Exception as e:
            logger.error(f"Error validating wallet: {str(e)}")
            return False
            
        return True
        
    async def update_token_list(self):
        """Update the list of monitored tokens"""
        if not self.token_discovery:
            logger.error("Token discovery not initialized")
            return
            
        try:
            discovered_tokens = await self.token_discovery.discover_tokens()
            
            # Reset token mappings
            self.token_addresses.clear()
            self.token_ids.clear()
            
            # Filter and add discovered tokens
            for token_id, token_data in discovered_tokens.items():
                symbol = token_data['symbol']
                
                # Skip blacklisted tokens
                if symbol in self.token_blacklist:
                    continue
                    
                # Only include whitelisted tokens if whitelist is not empty
                if self.token_whitelist and symbol not in self.token_whitelist:
                    continue
                    
                # Add token to mappings
                self.token_addresses[symbol] = token_data['address']
                self.token_ids[symbol] = token_id
                
            logger.info(f"Updated token list with {len(self.token_addresses)} tokens")
            
            # Log monitored tokens
            logger.info("\nMonitored tokens:")
            for symbol, address in self.token_addresses.items():
                logger.info(f"{symbol}: {address}")
                
        except Exception as e:
            logger.error(f"Error updating token list: {str(e)}")
    
    def is_connected(self) -> bool:
        """Check if Web3 is connected to the network and attempt reconnection if needed"""
        try:
            if self.w3 and self.w3.is_connected() and self.w3.eth.chain_id == self.chain_id:
                return True
                
            logger.warning("Connection lost, attempting to reconnect...")
            if self._reconnect():
                logger.info(f"Successfully reconnected to RPC: {self.rpc_url}")
                return True
                
            logger.error("Failed to connect to all RPC endpoints")
            return False
            
        except Exception as e:
            logger.error(f"Connection check failed: {str(e)}")
            return self._reconnect()

    async def close(self):
        """Clean up resources"""
        if self.notifier:
            await self.notifier.close()
        
        if hasattr(self.w3.provider, 'ws'):
            await self.w3.provider.ws.close()