from typing import Dict, List, Optional
import os
from dotenv import load_dotenv
from web3 import Web3
import json
import logging
from decimal import Decimal
import requests

from .market_utils import MarketUtils
from .notifications import TelegramNotifier
from .token_discovery import TokenDiscovery

logger = logging.getLogger(__name__)

class Config:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Node connection
        self.network_rpc = os.getenv('NETWORK_RPC_URL')
        self.backup_rpcs = os.getenv('BACKUP_RPC_URLS', '').split(',')
        
        # Wallet settings
        self.wallet_address = os.getenv('WALLET_ADDRESS')
        self.private_key = os.getenv('PRIVATE_KEY')
        
        # Trading parameters
        self.min_profit_threshold = float(os.getenv('MIN_PROFIT_THRESHOLD', '0.01'))
        self.max_gas_price = int(os.getenv('MAX_GAS_PRICE', '100'))
        self.slippage_tolerance = int(os.getenv('SLIPPAGE_TOLERANCE', '100'))  # basis points
        
        # Token discovery settings
        self.min_liquidity_usd = float(os.getenv('MIN_LIQUIDITY_USD', '5000').strip())
        self.min_volume_usd = float(os.getenv('MIN_VOLUME_USD', '1000').strip())
        self.token_blacklist = [
            addr.strip().lower() 
            for addr in os.getenv('TOKEN_BLACKLIST', '').split(',') 
            if addr.strip()
        ]
        self.token_whitelist = [
            addr.strip().lower() 
            for addr in os.getenv('TOKEN_WHITELIST', '').split(',') 
            if addr.strip()
        ]
        
        # DEX settings
        self.enabled_dexes = [
            dex.strip().lower() 
            for dex in os.getenv('ENABLED_DEXES', '').split(',') 
            if dex.strip()
        ]
        self.dex_weights = json.loads(os.getenv('DEX_WEIGHTS', '{}'))
        self.new_dex_delay = int(os.getenv('NEW_DEX_DELAY', '3600'))
        self.max_trade_hops = int(os.getenv('MAX_TRADE_HOPS', '3'))
        
        # Security settings
        self.max_exposure = float(os.getenv('MAX_EXPOSURE', '1.0'))
        self.verify_contracts = os.getenv('SMART_CONTRACT_VERIFICATION', 'true').lower() == 'true'
        self.min_token_age = int(os.getenv('MIN_TOKEN_AGE', '1'))
        self.required_audit_score = int(os.getenv('REQUIRED_AUDIT_SCORE', '70'))
        
        # Initialize Web3
        self.w3 = None
        self._initialize_web3()
        
        # Initialize statistics
        self.stats = {
            'opportunities_found': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_profit_eth': Decimal('0'),
            'total_profit_usd': Decimal('0'),
            'total_gas_used': Decimal('0')
        }

        # Initialize components
        self.market_utils = MarketUtils(self.w3)
        self.token_discovery = TokenDiscovery(self.w3)
        
        # Initialize notifier (optional)
        self.notifier = self._initialize_notifier()
        if self.notifier and not self.notifier.is_enabled():
            logger.info("Telegram notifications disabled - missing or invalid configuration")
            self.notifier = None
        
        # Trading pairs
        self.token_addresses = {}
        self.trading_pairs = {}

    def _test_node_connection(self, url: str) -> bool:
        """Test if a node is responsive"""
        try:
            headers = {'Content-Type': 'application/json'}
            payload = {
                'jsonrpc': '2.0',
                'method': 'eth_blockNumber',
                'params': [],
                'id': 1
            }
            response = requests.post(url, json=payload, headers=headers, timeout=5)
            return response.status_code == 200 and 'result' in response.json()
        except Exception as e:
            logger.debug(f"Node connection test failed for {url}: {str(e)}")
            return False

    def _initialize_web3(self):
        """Initialize Web3 with primary and backup nodes"""
        try:
            # Use default Ethereum nodes if none are specified
            if not self.network_rpc:
                self.network_rpc = "https://rpc.ankr.com/eth"
                self.backup_rpcs = [
                    "https://eth.rpc.blxrbdn.com",
                    "https://ethereum.publicnode.com",
                    "https://1rpc.io/eth"
                ]
            
            # Try primary node
            if self._test_node_connection(self.network_rpc):
                self.w3 = self._create_web3_instance(self.network_rpc)
                if self.w3 and self.w3.is_connected():
                    logger.info(f"Connected to primary node: {self.network_rpc}")
                    return
            
            # Try backup nodes
            for backup_rpc in self.backup_rpcs:
                if not backup_rpc:
                    continue
                if self._test_node_connection(backup_rpc):
                    try:
                        self.w3 = self._create_web3_instance(backup_rpc)
                        if self.w3 and self.w3.is_connected():
                            logger.info(f"Connected to backup node: {backup_rpc}")
                            return
                    except Exception as e:
                        logger.warning(f"Failed to connect to backup node {backup_rpc}: {str(e)}")
            
            raise ConnectionError("Failed to connect to any nodes")
            
        except Exception as e:
            logger.error(f"Error initializing Web3: {str(e)}")
            raise

    def _create_web3_instance(self, rpc_url: str) -> Optional[Web3]:
        """Create Web3 instance with appropriate provider"""
        try:
            provider = Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 30})
            w3 = Web3(provider)
            
            # Test the connection with a simple call
            try:
                w3.eth.block_number
            except Exception as e:
                logger.error(f"Failed to get block number from {rpc_url}: {str(e)}")
                return None
                
            return w3 if w3.is_connected() else None
        except Exception as e:
            logger.error(f"Failed to create Web3 instance for {rpc_url}: {str(e)}")
            return None

    def validate_config(self):
        """Validate required configuration settings"""
        required_settings = [
            ('PRIVATE_KEY', self.private_key),
            ('WALLET_ADDRESS', self.wallet_address)
        ]
        
        for setting_name, value in required_settings:
            if not value:
                logger.error(f'Missing required setting: {setting_name}')
                return False
        return True

    async def close(self):
        """Clean up resources"""
        try:
            if self.market_utils:
                await self.market_utils.close()
            if hasattr(self.w3.provider, 'disconnect'):
                await self.w3.provider.disconnect()
        except Exception as e:
            logger.error(f'Error during cleanup: {str(e)}')

    def _initialize_notifier(self) -> Optional[TelegramNotifier]:
        """Initialize Telegram notification handler"""
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if telegram_token and telegram_chat_id:
            return TelegramNotifier(telegram_token, telegram_chat_id)
        return None

    async def update_token_list(self):
        """Update tradeable token list"""
        try:
            discovered_tokens = await self.token_discovery.discover_tokens()
            
            valid_tokens = {}
            for symbol, token_data in discovered_tokens.items():
                if symbol in self.token_blacklist:
                    continue
                
                if self.token_whitelist and self.token_whitelist[0] and symbol not in self.token_whitelist:
                    continue

                if not token_data.get('pairs', []):
                    continue

                has_sufficient_liquidity = False
                total_volume_usd = 0

                for pair in token_data['pairs']:
                    liquidity = pair.get('reserve_usd', 0)
                    if liquidity >= self.min_liquidity_usd:
                        has_sufficient_liquidity = True
                        total_volume_usd += liquidity * 0.1

                if not has_sufficient_liquidity or total_volume_usd < self.min_volume_usd:
                    continue

                valid_tokens[symbol] = token_data['address']
            
            self.token_addresses = valid_tokens
            logger.info(f"Updated token list with {len(valid_tokens)} tokens")
            
        except Exception as e:
            logger.error(f"Error updating token list: {str(e)}")

    def is_connected(self) -> bool:
        """Check if connected to Ethereum node"""
        return self.w3 and self.w3.is_connected()

    async def is_gas_price_acceptable(self) -> bool:
        """Check if current gas price is below maximum"""
        try:
            current_gas_price = self.w3.from_wei(self.w3.eth.gas_price, 'gwei')
            return current_gas_price <= self.max_gas_price
        except Exception as e:
            logger.error(f"Error checking gas price: {str(e)}")
            return False

    def get_enabled_dexes(self) -> List[str]:
        """Get list of enabled DEXes"""
        if not self.enabled_dexes:
            return ['uniswap_v2', 'sushiswap', 'uniswap_v3', 'pancakeswap']
        return self.enabled_dexes

    def get_dex_weight(self, dex_id: str) -> float:
        """Get routing weight for a DEX"""
        return float(self.dex_weights.get(dex_id, 1.0))

    def is_new_dex_allowed(self, dex_id: str, creation_time: int) -> bool:
        """Check if a new DEX meets the minimum age requirement"""
        current_time = self.w3.eth.get_block('latest')['timestamp']
        return (current_time - creation_time) >= self.new_dex_delay

    def get_max_exposure(self, token_symbol: str) -> float:
        """Get maximum exposure allowed for a token"""
        return self.max_exposure