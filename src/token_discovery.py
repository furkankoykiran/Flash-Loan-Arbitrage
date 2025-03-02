import logging
import asyncio
from typing import Dict, List
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.contract import Contract
import json
import time
from decimal import Decimal

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# WETH address (checksummed)
WETH_ADDRESS = Web3.to_checksum_address('0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2')

# ABI for ERC20 and Uniswap V2 Pair
ERC20_ABI = json.loads('[{"constant":true,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]')
PAIR_ABI = json.loads('[{"constant":true,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},{"constant":true,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"},{"constant":true,"inputs":[],"name":"getReserves","outputs":[{"name":"reserve0","type":"uint112"},{"name":"reserve1","type":"uint112"},{"name":"blockTimestampLast","type":"uint32"}],"type":"function"}]')

# Initial pairs with checksummed addresses
INITIAL_PAIRS = [
    # Stablecoins
    Web3.to_checksum_address('0xa478c2975ab1ea89e8196811f51a7b7ade33eb11'),  # DAI-WETH
    Web3.to_checksum_address('0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc'),  # USDC-WETH
    Web3.to_checksum_address('0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852'),  # USDT-WETH
    # Popular DeFi tokens
    Web3.to_checksum_address('0xd3d2e2692501a5c9ca623199d38826e513033a17'),  # UNI-WETH
    Web3.to_checksum_address('0x9c83dce8ca20e9aaf9d3efc003b2ea62abc08351'),  # WBTC-WETH
    Web3.to_checksum_address('0xae461ca67b15dc8dc81ce7615e0320da1a9ab8d5'),  # LINK-WETH
    Web3.to_checksum_address('0x06da0fd433c1a5d7a4faa01111c044910a184553'),  # AAVE-WETH
    Web3.to_checksum_address('0x3041cbd36888becc7bbcbc0045e3b1f144466f5f'),  # USDC-USDT
    Web3.to_checksum_address('0xbb2b8038a1640196fbe3e38816f3e67cba72d940'),  # WBTC-WETH
    Web3.to_checksum_address('0x811beed0119b4afce20d2583eb608c6f7af1954f'),  # SHIB-WETH
]

class TokenDiscovery:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.discovered_tokens: Dict[str, Dict] = {}
        self.eth_price_usd = 2000  # Default ETH price, should be updated regularly

    def get_token_info(self, token_address: str) -> Dict:
        """Get token information from the blockchain"""
        try:
            # Ensure we're using a checksum address
            checksum_address = Web3.to_checksum_address(token_address)
            token_contract = self.w3.eth.contract(address=checksum_address, abi=ERC20_ABI)
            
            name = token_contract.functions.name().call()
            symbol = token_contract.functions.symbol().call()
            decimals = token_contract.functions.decimals().call()
            return {
                'name': name,
                'symbol': symbol,
                'decimals': decimals,
                'address': checksum_address
            }
        except ContractLogicError as e:
            logger.error(f"Error getting token info for {token_address}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting token info for {token_address}: {str(e)}")
            return None

    def get_pair_info(self, pair_address: str) -> Dict:
        """Get pair information from the blockchain"""
        try:
            # Ensure we're using a checksum address
            checksum_address = Web3.to_checksum_address(pair_address)
            pair_contract = self.w3.eth.contract(address=checksum_address, abi=PAIR_ABI)

            token0 = pair_contract.functions.token0().call()
            token1 = pair_contract.functions.token1().call()
            reserves = pair_contract.functions.getReserves().call()

            return {
                'token0': Web3.to_checksum_address(token0),
                'token1': Web3.to_checksum_address(token1),
                'reserve0': reserves[0],
                'reserve1': reserves[1]
            }
        except ContractLogicError as e:
            logger.error(f"Error getting pair info for {pair_address}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting pair info for {pair_address}: {str(e)}")
            return None

    def calculate_liquidity(self, reserve0: int, reserve1: int, decimals0: int, decimals1: int) -> float:
        """Calculate liquidity in USD"""
        try:
            weth_reserve = reserve0 if decimals0 == 18 else reserve1
            weth_liquidity = Decimal(weth_reserve) / Decimal(10 ** 18)
            return float(weth_liquidity * 2 * self.eth_price_usd)
        except Exception as e:
            logger.error(f"Error calculating liquidity: {str(e)}")
            return 0.0

    async def discover_tokens(self) -> Dict[str, Dict]:
        """Discover tokens from the blockchain using recursive discovery"""
        try:
            viable_tokens = {}
            processed_pairs = set()
            pairs_to_process = set(INITIAL_PAIRS)

            while pairs_to_process and len(viable_tokens) < 100:  # Limit to prevent infinite loops
                current_pair = pairs_to_process.pop()
                if current_pair in processed_pairs:
                    continue

                processed_pairs.add(current_pair)
                
                try:
                    # Get pair info
                    pair_info = self.get_pair_info(current_pair)
                    if not pair_info:
                        continue

                    # Process both tokens in the pair
                    for token_address in [pair_info['token0'], pair_info['token1']]:
                        if token_address.lower() == WETH_ADDRESS.lower():
                            continue

                        # Get token info
                        token_info = self.get_token_info(token_address)
                        if not token_info:
                            continue

                        # Calculate reserves and liquidity
                        is_token0 = token_address.lower() == pair_info['token0'].lower()
                        weth_reserve = pair_info['reserve1'] if is_token0 else pair_info['reserve0']
                        token_reserve = pair_info['reserve0'] if is_token0 else pair_info['reserve1']

                        liquidity_usd = self.calculate_liquidity(
                            pair_info['reserve0'],
                            pair_info['reserve1'],
                            18,
                            token_info['decimals']
                        )

                        # Add token if it meets liquidity threshold
                        if liquidity_usd >= 10000:
                            symbol = token_info['symbol']
                            
                            # Update existing token data or create new entry
                            if symbol in viable_tokens:
                                viable_tokens[symbol]['pairs'].append({
                                    'dex': 'uniswap_v2',
                                    'pair_address': current_pair,
                                    'reserve_weth': weth_reserve / (10 ** 18),
                                    'reserve_token': token_reserve / (10 ** token_info['decimals']),
                                    'reserve_usd': liquidity_usd,
                                    'volume_usd': 0,
                                    'price': (
                                        (weth_reserve / (10 ** 18)) /
                                        (token_reserve / (10 ** token_info['decimals'])) *
                                        self.eth_price_usd
                                    )
                                })
                            else:
                                viable_tokens[symbol] = {
                                    'symbol': symbol,
                                    'name': token_info['name'],
                                    'address': token_info['address'],
                                    'decimals': token_info['decimals'],
                                    'pairs': [{
                                        'dex': 'uniswap_v2',
                                        'pair_address': current_pair,
                                        'reserve_weth': weth_reserve / (10 ** 18),
                                        'reserve_token': token_reserve / (10 ** token_info['decimals']),
                                        'reserve_usd': liquidity_usd,
                                        'volume_usd': 0,
                                        'price': (
                                            (weth_reserve / (10 ** 18)) /
                                            (token_reserve / (10 ** token_info['decimals'])) *
                                            self.eth_price_usd
                                        )
                                    }]
                                }
                                logger.info(f"Discovered token: {symbol} with ${liquidity_usd:.2f} liquidity")

                                # Try to discover connected pairs
                                try:
                                    factory = self.w3.eth.contract(
                                        address=Web3.to_checksum_address('0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f'),  # Uniswap V2 Factory
                                        abi=[{"inputs":[{"internalType":"address","name":"tokenA","type":"address"},{"internalType":"address","name":"tokenB","type":"address"}],"name":"getPair","outputs":[{"internalType":"address","name":"pair","type":"address"}],"stateMutability":"view","type":"function"}]
                                    )
                                    new_pair = factory.functions.getPair(token_address, WETH_ADDRESS).call()
                                    if new_pair != '0x' + '0' * 40:  # Check if pair exists
                                        pairs_to_process.add(Web3.to_checksum_address(new_pair))
                                except Exception as e:
                                    logger.debug(f"Error discovering connected pairs for {symbol}: {str(e)}")

                except Exception as e:
                    logger.debug(f"Error processing pair {current_pair}: {str(e)}")
                    continue

                # Add small delay to prevent rate limiting
                await asyncio.sleep(0.1)

            self.discovered_tokens = viable_tokens
            logger.info(f"Discovered {len(viable_tokens)} tokens")
            return viable_tokens

        except Exception as e:
            logger.error(f"Error in token discovery: {str(e)}")
            return {}

    def get_discovered_tokens(self) -> Dict[str, Dict]:
        """Get the current list of discovered tokens"""
        return self.discovered_tokens.copy()

    async def update_token_data(self) -> None:
        """Update data for discovered tokens"""
        try:
            logger.info("Starting token data update...")
            new_tokens = await self.discover_tokens()
            self.discovered_tokens = new_tokens
            logger.info(f"Updated {len(new_tokens)} tokens' data")
        except Exception as e:
            logger.error(f"Error updating token data: {str(e)}")