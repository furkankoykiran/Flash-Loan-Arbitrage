import logging
from typing import Dict, Tuple, List
from decimal import Decimal
import aiohttp
from web3 import Web3
import asyncio
from datetime import datetime

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

    def __init__(self, w3: Web3):
        self.w3 = w3
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
        """Calculate trade profitability with minimal threshold"""
        try:
            # Convert amount to decimal
            amount_decimal = Decimal(amount) / Decimal(10 ** decimals)
            
            # Get token price
            token_price = await self.get_token_price(token_symbol.lower())
            token_price_decimal = Decimal(str(token_price))
            
            # Get gas price
            gas_price = await self.get_gas_price()
            gas_price_gwei = self.w3.from_wei(gas_price, 'gwei')
            
            # Estimate gas costs (300k gas units per swap)
            total_gas = 600000  # Two swaps
            gas_cost_wei = gas_price * total_gas
            gas_cost_eth = Decimal(self.w3.from_wei(gas_cost_wei, 'ether'))
            
            # Get ETH price for gas cost calculation
            eth_price = await self.get_eth_price()
            gas_cost_usd = gas_cost_eth * Decimal(str(eth_price))
            
            # Calculate DEX fees (0.3% per swap)
            dex_fee = Decimal('0.003')  # 0.3%
            total_dex_fees = amount_decimal * dex_fee * Decimal('2')  # Two swaps
            
            # Calculate potential profit
            gross_profit_token = amount_decimal * Decimal('0.997') * Decimal('0.997')  # After DEX fees
            gross_profit_usd = gross_profit_token * token_price_decimal
            
            # Calculate net profit
            net_profit_usd = gross_profit_usd - gas_cost_usd
            net_profit_token = net_profit_usd / token_price_decimal
            
            # Calculate ROI
            investment_usd = amount_decimal * token_price_decimal
            roi = (net_profit_usd / investment_usd * 100) if investment_usd > 0 else Decimal('0')
            
            # Log analysis
            logger.info("\n🔍 Profitability Analysis:")
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
                'roi': roi
            }
            
        except Exception as e:
            logger.error(f"Error calculating profitability: {str(e)}")
            return {
                'profitable': False,
                'error': str(e)
            }

    async def get_network_status(self) -> Dict:
        """Get current network status"""
        try:
            eth_price = await self.get_eth_price()
            gas_price = self.w3.from_wei(await self.get_gas_price(), 'gwei')
            block_number = self.w3.eth.block_number
            
            logger.info(f"\nNetwork Status:")
            logger.info(f"ETH Price: ${eth_price:.2f}")
            logger.info(f"Gas Price: {gas_price:.1f} gwei")
            logger.info(f"Block Number: {block_number}")
            
            return {
                'block_number': block_number,
                'gas_price_gwei': gas_price,
                'eth_price_usd': eth_price
            }
        except Exception as e:
            logger.error(f"Failed to get network status: {str(e)}")
            return {
                'block_number': 0,
                'gas_price_gwei': 0,
                'eth_price_usd': 0
            }

    def get_min_amount(self, token_symbol: str) -> Decimal:
        """Get minimum amount for a token"""
        return self.MIN_AMOUNTS.get(token_symbol, Decimal('0'))

    def format_amount(self, amount: int, decimals: int) -> str:
        """Format token amount with proper decimals"""
        return f"{Decimal(amount) / Decimal(10 ** decimals):.6f}"