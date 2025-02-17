from typing import List, Dict
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
        self.market_utils = config.market_utils
        self.notifier = config.notifier
        self.start_time = datetime.now()
        self.trading_pairs = {}
        self.token_contracts = {}
        self._initialized = False
        self.uniswap_router = None
        self.sushiswap_router = None
        self.wbtc_contract = None
        self.usdt_contract = None
        self._shutdown = False

    async def initialize(self):
        """Initialize the bot asynchronously"""
        if self._initialized:
            return

        try:
            print("\n🤖 Initializing Arbitrage Bot...")
            
            # Initialize contracts
            print("\nConnecting to DEX routers...")
            self.uniswap_router = self.contracts.get_dex_router(self.config.uniswap_router)
            print("✅ Connected to Uniswap Router")
            self.sushiswap_router = self.contracts.get_dex_router(self.config.sushiswap_router)
            print("✅ Connected to Sushiswap Router")
            
            # Initialize token discovery and get initial token list
            print("\nDiscovering tokens...")
            await self.config.update_token_list()
            
            # Initialize pairs and approve tokens
            await self._initialize_pairs()
            
            print(f"\n✅ Initialized with {len(self.config.token_addresses)} tokens")
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
        """Initialize trading pairs and approve tokens"""
        try:
            print("Initializing trading pairs...")
            
            # Clear existing pairs and contracts
            self.trading_pairs = {}
            new_token_contracts = {}
            
            # Get discovered tokens data
            discovered_tokens = self.config.token_discovery.get_discovered_tokens()
            
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
                for pair in token_data.get('pairs', []):
                    pair_name = f"{symbol}-{pair['dex'].upper()}"
                    self.trading_pairs[pair_name] = {
                        'tokens': [symbol, 'WETH'],  # Assuming pairs with WETH
                        'addresses': {
                            symbol: address,
                            'WETH': self.config.token_addresses.get('WETH')
                        },
                        'dex': pair['dex'],
                        'liquidity_usd': pair['liquidity_usd'],
                        'volume_usd': pair['volume_usd']
                    }
            
            # Update token contracts
            self.token_contracts = new_token_contracts
            
            print(f"\nInitialized {len(self.trading_pairs)} trading pairs")
            
            print("\nApproving tokens for trading...")
            # Approve tokens
            for token_symbol, contract in self.token_contracts.items():
                await self._approve_token(
                    contract.address,
                    [self.config.uniswap_router, self.config.sushiswap_router]
                )
                print(f"✅ {token_symbol} approved for trading")
                
        except Exception as e:
            logger.error(f"Error initializing pairs: {str(e)}")
            raise

    async def _approve_token(self, token_address: str, spender_addresses: List[str]):
        """Approve token for multiple spenders"""
        for spender in spender_addresses:
            try:
                await self.contracts.check_and_approve_token(
                    token_address,
                    spender,
                    self.config.wallet_address,
                    self.config.private_key
                )
            except Exception as e:
                logger.error(f"Error approving token {token_address} for {spender}: {str(e)}")
                raise

    async def monitor_opportunities(self):
        """Monitor for arbitrage opportunities"""
        if not self._initialized:
            raise RuntimeError("Bot not initialized. Call initialize() first.")

        print("\n🔍 Starting arbitrage monitoring...")
        print(f"Monitoring {len(self.trading_pairs)} trading pairs:")
        for pair_name in self.trading_pairs.keys():
            print(f"• {pair_name}")
        
        print(f"\nMinimum profit threshold: {self.config.min_profit_threshold} ETH")
        print(f"Maximum gas price: {self.config.max_gas_price} gwei")
        print("\nPress Ctrl+C to stop monitoring\n")
        
        while not self._shutdown:
            try:
                if self._shutdown:
                    break
                    
                if not self.config.is_connected():
                    logger.error("Lost connection to node")
                    await asyncio.sleep(30)
                    continue

                # Check opportunities for each pair
                for pair_name, pair_data in self.trading_pairs.items():
                    await self._check_pair_opportunity(pair_name, pair_data)
                
                # Send periodic status update every 5 minutes
                current_time = datetime.now()
                if not hasattr(self, 'last_status_update') or (current_time - self.last_status_update).seconds >= 300:
                    if self.notifier:
                        eth_balance = self.w3.eth.get_balance(self.config.wallet_address)
                        eth_balance_formatted = self.w3.from_wei(eth_balance, 'ether')
                        
                        token_balances = {}
                        for symbol, contract in self.token_contracts.items():
                            balance = await self.contracts.get_token_balance(contract, self.config.wallet_address)
                            decimals = await self.contracts.get_token_decimals(contract)
                            formatted_balance = balance / 10**decimals
                            token_balances[symbol] = f"{formatted_balance:.6f}"
                        
                        runtime = current_time - self.start_time
                        hours = runtime.total_seconds() / 3600
                        
                        await self.notifier.send_status_update({
                            'eth_price': await self.market_utils.get_eth_price(),
                            'gas_price': self.w3.from_wei(self.w3.eth.gas_price, 'gwei'),
                            'block_number': self.w3.eth.block_number,
                            'eth_balance': f"{eth_balance_formatted:.6f}",
                            'token_balances': token_balances,
                            'opportunities_found': self.config.stats['opportunities_found'],
                            'successful_trades': self.config.stats['successful_trades'],
                            'failed_trades': self.config.stats['failed_trades'],
                            'total_profit': f"{self.config.stats['total_profit_eth']:.6f}",
                            'start_time': self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                            'runtime_hours': f"{hours:.2f}"
                        })
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

    async def _check_pair_opportunity(self, pair_name: str, pair_data: Dict):
        """Check arbitrage opportunity for a specific pair"""
        try:
            token0_symbol, token1_symbol = pair_data['tokens']
            token0_contract = self.token_contracts[token0_symbol]
            token1_contract = self.token_contracts[token1_symbol]
            
            # Get balances
            token0_balance = await self.contracts.get_token_balance(token0_contract, self.config.wallet_address)
            token1_balance = await self.contracts.get_token_balance(token1_contract, self.config.wallet_address)
            
            if token0_balance > 0:
                await self._check_token_arbitrage(
                    token0_symbol,
                    token0_balance,
                    token0_contract,
                    token1_contract
                )
                
            if token1_balance > 0:
                await self._check_token_arbitrage(
                    token1_symbol,
                    token1_balance,
                    token1_contract,
                    token0_contract
                )
                
        except Exception as e:
            logger.error(f"Error checking {pair_name} opportunity: {str(e)}")

    async def _check_token_arbitrage(
        self,
        token_symbol: str,
        balance: int,
        token_contract: Contract,
        other_token_contract: Contract
    ):
        """Check arbitrage opportunity for a specific token"""
        try:
            # Get token decimals
            decimals = await self.contracts.get_token_decimals(token_contract)
            
            # Calculate arbitrage
            path1 = [token_contract.address, other_token_contract.address]
            path2 = [other_token_contract.address, token_contract.address]
            
            opportunity = await self.market_utils.calculate_profitability(
                balance,
                decimals,
                path1,
                path2,
                token_symbol,
                'uniswap',
                'sushiswap'
            )
            
            if opportunity['profitable']:
                logger.info(f"\n💰 Found profitable {token_symbol} arbitrage!")
                logger.info(f"Expected profit: {opportunity['net_profit_token']:.6f} {token_symbol}")
                logger.info(f"ROI: {opportunity['roi']:.2f}%")
                
                if await self.config.is_gas_price_acceptable():
                    # Execute trade if profitable
                    await self._execute_arbitrage(
                        token_symbol,
                        balance,
                        path1,
                        path2,
                        opportunity
                    )
                else:
                    logger.info("⚠️ Gas price too high, skipping trade")
            
        except Exception as e:
            logger.error(f"Error checking {token_symbol} arbitrage: {str(e)}")

    async def _execute_arbitrage(
        self,
        token_symbol: str,
        amount: int,
        path1: List[str],
        path2: List[str],
        opportunity: Dict
    ):
        """Execute arbitrage trades"""
        try:
            logger.info(f"\n🔄 Executing {token_symbol} arbitrage...")
            
            # Execute trades
            success = await self.contracts.execute_trades(
                amount,
                path1,
                path2,
                self.config.wallet_address,
                self.config.private_key
            )
            
            if success:
                logger.info("✅ Arbitrage executed successfully!")
                # Update statistics
                self.config.stats['successful_trades'] += 1
                self.config.stats['total_profit_eth'] += opportunity['net_profit_token']
                self.config.stats['total_profit_usd'] += opportunity['net_profit_usd']
                
                if self.notifier:
                    await self.notifier.send_execution_result(True, {
                        'token_symbol': token_symbol,
                        'profit_token': opportunity['net_profit_token'],
                        'profit_usd': opportunity['net_profit_usd'],
                        'roi': opportunity['roi']
                    })
            else:
                logger.error("❌ Arbitrage execution failed")
                self.config.stats['failed_trades'] += 1
                
                if self.notifier:
                    await self.notifier.send_execution_result(False, {
                        'error': 'Trade execution failed'
                    })
            
        except Exception as e:
            logger.error(f"Error executing arbitrage: {str(e)}")
            self.config.stats['failed_trades'] += 1
            
            if self.notifier:
                await self.notifier.send_execution_result(False, {
                    'error': str(e)
                })
                
    async def stop(self):
        """Stop the bot gracefully"""
        logger.info("\n🛑 Stopping bot...")
        self._shutdown = True
        await self.cleanup()
        logger.info("Bot stopped successfully")
