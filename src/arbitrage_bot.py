from typing import List, Dict, Optional
from web3 import Web3
from web3.contract import Contract
from decimal import Decimal
import time
import logging
from datetime import datetime
import asyncio

from .config import Config
from .contracts import ContractInterface
from .market_utils import MarketUtils

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class ArbitrageBot:
    def __init__(self, config: Config):
        self.config = config
        self.w3 = config.w3
        self.contracts = ContractInterface(self.w3, config)
        self.market_utils = MarketUtils(self.w3, self.contracts)
        self.notifier = config.notifier
        self.start_time = datetime.now()
        self.trading_pairs = {}
        self.token_contracts = {}
        self._initialized = False
        self._shutdown = False
        self.dex_routers = {}
        self.min_liquidity_usd = 5000   # Lower minimum liquidity to $5k
        self.max_hops = 3  # Maximum number of DEX hops in a path

        # Initialize statistics
        self.stats = {
            'opportunities_found': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_profit_eth': Decimal('0'),
            'total_profit_usd': Decimal('0'),
            'total_gas_used': Decimal('0')
        }

    async def initialize(self):
        """Initialize the bot asynchronously"""
        if self._initialized:
            return

        try:
            print("\n🤖 Initializing Multi-DEX Arbitrage Bot...")
            
            # Initialize DEX routers
            print("\nConnecting to DEX routers...")
            supported_dexes = self.contracts.get_supported_dexes()
            for dex_id in supported_dexes:
                dex_info = self.contracts.get_dex_info(dex_id)
                if not dex_info:
                    continue
                    
                router = self.contracts.get_dex_router(dex_id)
                if router:
                    self.dex_routers[dex_id] = router
                    print(f"✅ Connected to {dex_info['name']}")
            
            # Initialize token discovery
            print("\nDiscovering tokens...")
            await self.config.update_token_list()
            
            # Initialize pairs
            await self._initialize_pairs()
            
            print(f"\n✅ Initialized with {len(self.config.token_addresses)} tokens")
            print(f"✅ Connected to {len(self.dex_routers)} DEXes")
            self._initialized = True
            
            # Start token list update loop
            asyncio.create_task(self._token_update_loop())
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {str(e)}")
            raise

    async def _token_update_loop(self):
        """Periodically update the token list"""
        while not self._shutdown:
            try:
                await asyncio.sleep(300)  # Update every 5 minutes
                if not self._shutdown:
                    await self.config.update_token_list()
                    await self._initialize_pairs()
            except Exception as e:
                logger.error(f"Error in token update loop: {str(e)}")
                await asyncio.sleep(60)  # Wait before retrying

    async def cleanup(self):
        """Cleanup resources"""
        try:
            if self.market_utils:
                await self.market_utils.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def _initialize_pairs(self):
        """Initialize trading pairs"""
        try:
            print("Initializing trading pairs...")
            
            # Clear existing pairs and contracts
            self.trading_pairs = {}
            new_token_contracts = {}
            
            # Get discovered tokens data
            discovered_tokens = self.config.token_discovery.get_discovered_tokens()
            supported_dexes = self.contracts.get_supported_dexes()
            
            for token_id, token_data in discovered_tokens.items():
                symbol = token_data['symbol']
                address = token_data['address']
                
                # Skip if token is not in configured addresses
                if symbol not in self.config.token_addresses:
                    continue
                
                # Initialize or reuse token contract
                if symbol in self.token_contracts:
                    new_token_contracts[symbol] = self.token_contracts[symbol]
                else:
                    new_token_contracts[symbol] = self.contracts.get_token_contract(address)
                    print(f"✅ Initialized {symbol} contract")
                
                # Process DEX pairs
                for dex_id in supported_dexes:
                    if not await self.contracts.verify_dex_security(dex_id):
                        continue

                    # Check liquidity on this DEX
                    if await self.market_utils.check_liquidity(
                        dex_id,
                        address,
                        self.contracts.TOKENS['WETH'],
                        self.min_liquidity_usd
                    ):
                        pair_name = f"{symbol}-{dex_id.upper()}"
                        self.trading_pairs[pair_name] = {
                            'token': symbol,
                            'dex_id': dex_id,
                            'address': address,
                        }
            
            # Update token contracts
            self.token_contracts = new_token_contracts
            print(f"\nInitialized {len(self.trading_pairs)} trading pairs")
                
        except Exception as e:
            logger.error(f"Error initializing pairs: {str(e)}")
            raise

    async def monitor_opportunities(self):
        """Monitor for arbitrage opportunities across all DEXes"""
        if not self._initialized:
            raise RuntimeError("Bot not initialized. Call initialize() first.")

        print("\n🔍 Starting multi-DEX arbitrage monitoring...")
        print(f"Monitoring {len(self.trading_pairs)} trading pairs across {len(self.dex_routers)} DEXes:")
        for pair_name in self.trading_pairs.keys():
            print(f"• {pair_name}")
        
        print(f"\nMinimum profit threshold: {self.config.min_profit_threshold} ETH")
        print(f"Maximum gas price: {self.config.max_gas_price} gwei")
        print(f"Maximum path hops: {self.max_hops}")
        print("\nPress Ctrl+C to stop monitoring\n")
        
        self.last_status_update = datetime.now()  # Initialize last update time
        
        while not self._shutdown:
            try:
                if self._shutdown:
                    break
                    
                if not self.config.is_connected():
                    logger.error("Lost connection to node")
                    await asyncio.sleep(30)
                    continue

                # Check opportunities for each token
                for pair_name, pair_data in self.trading_pairs.items():
                    await self._check_token_opportunities(
                        pair_data['token'],
                        pair_data['address']
                    )
                
                # Send periodic status update every 5 minutes
                current_time = datetime.now()
                if (current_time - self.last_status_update).seconds >= 300:
                    if self.notifier:
                        await self._send_status_update()
                    self.last_status_update = current_time
                
                # Check shutdown flag before sleep
                if self._shutdown:
                    break
                # Small delay between checks
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info("Monitoring cancelled")
                self._shutdown = True
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(1)

    async def _check_token_opportunities(self, token_symbol: str, token_address: str):
        """Check arbitrage opportunities for a specific token across all DEXes"""
        try:
            # Get token balance
            token_contract = self.token_contracts[token_symbol]
            balance = await self.contracts.get_token_balance(token_contract, self.config.wallet_address)
            
            if balance == 0:
                return

            # Find best arbitrage path
            best_path = await self.market_utils.find_arbitrage_path(
                token_address,
                balance,
                self.max_hops
            )

            if best_path and best_path['profit_data']['profitable']:
                profit_data = best_path['profit_data']
                dex_path = best_path['dex_path']

                logger.info(f"\n💰 Found profitable {token_symbol} arbitrage opportunity!")
                logger.info(f"Path: {' -> '.join(dex_path)}")
                logger.info(f"Expected profit: ${float(profit_data['net_profit_usd']):.2f}")
                logger.info(f"ROI: {float(profit_data['roi']):.2f}%")

                self.stats['opportunities_found'] += 1

                if await self.config.is_gas_price_acceptable():
                    await self._execute_arbitrage_path(
                        token_symbol,
                        balance,
                        dex_path,
                        profit_data
                    )
                else:
                    logger.info("⚠️ Gas price too high, skipping trade")

        except Exception as e:
            logger.error(f"Error checking {token_symbol} opportunities: {str(e)}")

    async def _execute_arbitrage_path(
        self,
        token_symbol: str,
        amount: int,
        dex_path: List[str],
        profit_data: Dict
    ):
        """Execute arbitrage trades along the optimal path"""
        try:
            logger.info(f"\n🔄 Executing {token_symbol} arbitrage along path: {' -> '.join(dex_path)}")
            
            current_amount = amount
            success = True
            
            # Execute trades along the path
            for i in range(len(dex_path) - 1):
                from_dex = dex_path[i]
                to_dex = dex_path[i + 1]
                
                # Execute trade between these DEXes
                result = await self.contracts.execute_trade(
                    from_dex,
                    current_amount,
                    [self.token_contracts[token_symbol].address],
                    self.config.wallet_address,
                    int(time.time()) + 300,  # 5 minutes deadline
                    self.config.private_key
                )
                
                if not result:
                    success = False
                    break
                
                # Update amount for next trade
                current_amount = await self.contracts.get_token_balance(
                    self.token_contracts[token_symbol],
                    self.config.wallet_address
                )
            
            if success:
                logger.info("✅ Arbitrage executed successfully!")
                # Update statistics
                self.stats['successful_trades'] += 1
                self.stats['total_profit_eth'] += Decimal(str(profit_data['net_profit_eth']))
                self.stats['total_profit_usd'] += Decimal(str(profit_data['net_profit_usd']))
                
                if self.notifier and self.notifier.is_enabled():
                    await self.notifier.send_execution_result(True, {
                        'token_symbol': token_symbol,
                        'profit_token': profit_data['net_profit_eth'],
                        'profit_usd': profit_data['net_profit_usd'],
                        'roi': profit_data['roi'],
                        'path': ' -> '.join(dex_path)
                    })
            else:
                logger.error("❌ Arbitrage execution failed")
                self.stats['failed_trades'] += 1
                
                if self.notifier and self.notifier.is_enabled():
                    await self.notifier.send_execution_result(False, {
                        'error': 'Trade execution failed'
                    })
            
        except Exception as e:
            logger.error(f"Error executing arbitrage: {str(e)}")
            self.stats['failed_trades'] += 1
            
            if self.notifier and self.notifier.is_enabled():
                await self.notifier.send_execution_result(False, {
                    'error': str(e)
                })

    async def _send_status_update(self):
        """Send periodic status update"""
        try:
            network_status = await self.market_utils.get_network_status()
            eth_balance = self.w3.eth.get_balance(self.config.wallet_address)
            eth_balance_formatted = self.w3.from_wei(eth_balance, 'ether')
            
            token_balances = {}
            for symbol, contract in self.token_contracts.items():
                balance = await self.contracts.get_token_balance(contract, self.config.wallet_address)
                decimals = await self.contracts.get_token_decimals(contract)
                formatted_balance = balance / 10**decimals
                token_balances[symbol] = formatted_balance
            
            runtime = datetime.now() - self.start_time
            hours = runtime.total_seconds() / 3600

            # Log network status to console
            logger.info("\nNetwork Status:")
            logger.info(f"ETH Price: ${network_status['eth_price_usd']}")
            logger.info(f"Gas Price: {network_status['gas_price_gwei']} gwei")
            logger.info(f"Block Number: {network_status['block_number']}")
            logger.info(f"Active DEXes: {len(self.dex_routers)}")
            
            # Only send Telegram notification if notifier is properly configured
            if self.notifier and self.notifier.is_enabled():
                await self.notifier.send_status_update({
                    'eth_price': network_status['eth_price_usd'],
                    'gas_price': network_status['gas_price_gwei'],
                    'block_number': network_status['block_number'],
                    'active_dexes': len(self.dex_routers),
                    'eth_balance': eth_balance_formatted,
                    'token_balances': token_balances,
                    'opportunities_found': self.stats['opportunities_found'],
                    'successful_trades': self.stats['successful_trades'],
                    'failed_trades': self.stats['failed_trades'],
                    'total_profit_eth': self.stats['total_profit_eth'],
                    'total_profit_usd': self.stats['total_profit_usd'],
                    'start_time': self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    'runtime_hours': hours
                })
        except Exception as e:
            logger.error(f"Error sending status update: {str(e)}")

    async def stop(self):
        """Stop the bot gracefully"""
        logger.info("\n🛑 Stopping bot...")
        self._shutdown = True
        await self.cleanup()
        logger.info("Bot stopped successfully")
