import logging
from typing import Dict, Tuple, List, Optional
from decimal import Decimal
import aiohttp
from web3 import Web3
import asyncio
from datetime import datetime
from itertools import permutations

logger = logging.getLogger(__name__)

class MarketUtils:
    # Minimum amounts for profitability check (in token decimals)
    MIN_AMOUNTS = {
        'WETH': Decimal('0.01'),    # 0.01 ETH
        'WBTC': Decimal('0.001'),   # 0.001 BTC
        'USDT': Decimal('100'),     # 100 USDT
        'USDC': Decimal('100'),     # 100 USDC
        'DAI': Decimal('100')       # 100 DAI
    }

    def __init__(self, w3: Web3, contracts=None):
        self.w3 = w3
        self.contracts = contracts
        self._price_cache = {}
        self._last_update = 0
        self._session = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self):
        """Ensure aiohttp session exists with lock protection"""
        async with self._lock:
            if self._session is None:
                self._session = aiohttp.ClientSession()

    async def close(self):
        """Close aiohttp session"""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_token_price(self, token_id: str) -> float:
        """Get token price in USD using async HTTP request"""
        try:
            # Check cache first (30 seconds cache)
            cache_age = datetime.now().timestamp() - self._last_update
            if token_id in self._price_cache and cache_age < 30:
                return self._price_cache[token_id]

            await self._ensure_session()
            
            async with self._session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": token_id,
                    "vs_currencies": "usd"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data[token_id]["usd"])
                    self._price_cache[token_id] = price
                    self._last_update = datetime.now().timestamp()
                    return price
                else:
                    logger.error(f"Failed to fetch {token_id} price: {response.status}")
                    return 0.0
        except Exception as e:
            logger.error(f"Error fetching {token_id} price: {str(e)}")
            return 0.0

    async def get_eth_price(self) -> float:
        """Get current ETH price in USD"""
        return await self.get_token_price("ethereum")

    async def get_gas_price(self) -> int:
        """Get current gas price in wei"""
        try:
            gas_price = self.w3.eth.gas_price
            return gas_price
        except Exception as e:
            logger.error(f"Failed to get gas price: {str(e)}")
            return 0

    async def find_arbitrage_path(
        self,
        token_address: str,
        amount: int,
        max_hops: int = 3
    ) -> Optional[Dict]:
        """Find the most profitable arbitrage path across multiple DEXes"""
        try:
            # Get all supported DEXes
            dexes = self.contracts.get_supported_dexes()
            verified_dexes = [dex for dex in dexes if await self.contracts.verify_dex_security(dex)]

            best_path = None
            best_profit = Decimal('0')

            # Generate paths with different DEX combinations
            for path_length in range(2, max_hops + 1):
                for dex_path in permutations(verified_dexes, path_length):
                    result = await self.calculate_path_profitability(
                        token_address,
                        amount,
                        list(dex_path)
                    )

                    if result['profitable'] and result['net_profit_usd'] > best_profit:
                        best_profit = result['net_profit_usd']
                        best_path = {
                            'dex_path': dex_path,
                            'profit_data': result
                        }

            return best_path

        except Exception as e:
            logger.error(f"Error finding arbitrage path: {str(e)}")
            return None

    async def calculate_path_profitability(
        self,
        token_address: str,
        amount: int,
        dex_path: List[str]
    ) -> Dict:
        """Calculate profitability for a specific DEX path"""
        try:
            current_amount = amount
            total_gas_cost = 0
            total_fees = Decimal('0')
            token_price = Decimal(str(await self.get_token_price(token_address.lower())))
            eth_price = Decimal(str(await self.get_eth_price()))

            # Calculate trade outcome through the path
            for dex_id in dex_path:
                dex_info = self.contracts.get_dex_info(dex_id)
                if not dex_info:
                    continue

                # Add gas cost for this hop
                gas_price = await self.get_gas_price()
                hop_gas = 300000  # Estimated gas per swap
                total_gas_cost += hop_gas * gas_price

                # Calculate DEX fees
                fee_rate = Decimal(str(dex_info['fee']))
                fee_amount = Decimal(str(current_amount)) * fee_rate
                total_fees += fee_amount

                # Calculate output amount
                current_amount = int(Decimal(str(current_amount)) * (Decimal('1') - fee_rate))

            # Calculate costs and profits
            gas_cost_eth = Decimal(self.w3.from_wei(total_gas_cost, 'ether'))
            gas_cost_usd = gas_cost_eth * eth_price

            initial_value = Decimal(str(amount)) * token_price
            final_value = Decimal(str(current_amount)) * token_price
            gross_profit_usd = final_value - initial_value
            net_profit_usd = gross_profit_usd - gas_cost_usd

            # Calculate ROI
            roi = (net_profit_usd / initial_value * 100) if initial_value > 0 else Decimal('0')

            return {
                'profitable': net_profit_usd > 0,
                'net_profit_usd': net_profit_usd,
                'gas_cost_eth': gas_cost_eth,
                'gas_cost_usd': gas_cost_usd,
                'total_fees_token': total_fees,
                'final_amount': current_amount,
                'roi': roi,
                'dex_path': dex_path
            }

        except Exception as e:
            logger.error(f"Error calculating path profitability: {str(e)}")
            return {
                'profitable': False,
                'error': str(e)
            }

    async def calculate_profitability(
        self,
        amount: int,
        decimals: int,
        path1: List[str],
        path2: List[str],
        token_symbol: str,
        input_dex: str,
        output_dex: str
    ) -> Dict:
        """Calculate trade profitability between two specific DEXes"""
        try:
            # Convert amount to decimal
            amount_decimal = Decimal(amount) / Decimal(10 ** decimals)
            
            # Get token price
            token_price = await self.get_token_price(token_symbol.lower())
            token_price_decimal = Decimal(str(token_price))
            
            # Get gas price and calculate costs
            gas_price = await self.get_gas_price()
            gas_price_gwei = self.w3.from_wei(gas_price, 'gwei')
            
            # Get DEX fees
            input_dex_info = self.contracts.get_dex_info(input_dex)
            output_dex_info = self.contracts.get_dex_info(output_dex)
            
            if not input_dex_info or not output_dex_info:
                raise ValueError("Invalid DEX specified")
            
            input_fee = Decimal(str(input_dex_info['fee']))
            output_fee = Decimal(str(output_dex_info['fee']))
            
            # Estimate gas costs (300k gas units per swap)
            total_gas = 600000  # Two swaps
            gas_cost_wei = gas_price * total_gas
            gas_cost_eth = Decimal(self.w3.from_wei(gas_cost_wei, 'ether'))
            
            # Get ETH price for gas cost calculation
            eth_price = await self.get_eth_price()
            gas_cost_usd = gas_cost_eth * Decimal(str(eth_price))
            
            # Calculate DEX fees
            total_dex_fees = amount_decimal * (input_fee + output_fee)
            
            # Calculate potential profit
            fee_multiplier = (Decimal('1') - input_fee) * (Decimal('1') - output_fee)
            gross_profit_token = amount_decimal * fee_multiplier
            gross_profit_usd = gross_profit_token * token_price_decimal
            
            # Calculate net profit
            net_profit_usd = gross_profit_usd - gas_cost_usd
            net_profit_token = net_profit_usd / token_price_decimal
            
            # Calculate ROI
            investment_usd = amount_decimal * token_price_decimal
            roi = (net_profit_usd / investment_usd * 100) if investment_usd > 0 else Decimal('0')
            
            # Log analysis
            logger.info(f"\n🔍 Profitability Analysis ({input_dex} -> {output_dex}):")
            logger.info(f"Token: {token_symbol}")
            logger.info(f"Amount: {amount_decimal} (${float(amount_decimal * token_price_decimal):.2f})")
            logger.info(f"Gas Cost: {gas_cost_eth:.6f} ETH (${float(gas_cost_usd):.2f})")
            logger.info(f"DEX Fees: {total_dex_fees} {token_symbol}")
            logger.info(f"Net Profit: {net_profit_token:.6f} {token_symbol} (${float(net_profit_usd):.2f})")
            logger.info(f"ROI: {float(roi):.2f}%")
            
            return {
                'profitable': net_profit_usd > 0,
                'net_profit_token': net_profit_token,
                'net_profit_usd': net_profit_usd,
                'gas_cost_eth': gas_cost_eth,
                'gas_cost_usd': gas_cost_usd,
                'roi': roi,
                'input_dex': input_dex,
                'output_dex': output_dex
            }
            
        except Exception as e:
            logger.error(f"Error calculating profitability: {str(e)}")
            return {
                'profitable': False,
                'error': str(e)
            }

    async def check_liquidity(
        self,
        dex_id: str,
        token_a: str,
        token_b: str,
        min_liquidity_usd: float
    ) -> bool:
        """Check if a token pair has sufficient liquidity on a DEX"""
        try:
            reserves = await self.contracts.get_dex_reserves(dex_id, token_a, token_b)
            if not reserves:
                return False

            # Get token prices
            token_a_price = await self.get_token_price(token_a.lower())
            token_b_price = await self.get_token_price(token_b.lower())

            # Calculate liquidity in USD
            liquidity_usd = (
                (reserves[0] * token_a_price) +
                (reserves[1] * token_b_price)
            )

            return liquidity_usd >= min_liquidity_usd

        except Exception as e:
            logger.error(f"Error checking liquidity: {str(e)}")
            return False

    async def get_network_status(self) -> Dict:
        """Get current network status"""
        try:
            eth_price = await self.get_eth_price()
            gas_price = self.w3.from_wei(await self.get_gas_price(), 'gwei')
            block_number = self.w3.eth.block_number
            
            # Get active DEXes count
            active_dexes = len(self.contracts.get_supported_dexes()) if self.contracts else 0
            
            logger.info(f"\nNetwork Status:")
            logger.info(f"ETH Price: ${eth_price:.2f}")
            logger.info(f"Gas Price: {gas_price:.1f} gwei")
            logger.info(f"Block Number: {block_number}")
            logger.info(f"Active DEXes: {active_dexes}")
            
            return {
                'block_number': block_number,
                'gas_price_gwei': gas_price,
                'eth_price_usd': eth_price,
                'active_dexes': active_dexes
            }
        except Exception as e:
            logger.error(f"Failed to get network status: {str(e)}")
            return {
                'block_number': 0,
                'gas_price_gwei': 0,
                'eth_price_usd': 0,
                'active_dexes': 0
            }

    def get_min_amount(self, token_symbol: str) -> Decimal:
        """Get minimum amount for a token"""
        return self.MIN_AMOUNTS.get(token_symbol, Decimal('0'))

    def format_amount(self, amount: int, decimals: int) -> str:
        """Format token amount with proper decimals"""
        return f"{Decimal(amount) / Decimal(10 ** decimals):.6f}"