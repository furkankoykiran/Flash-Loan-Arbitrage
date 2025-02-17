import logging
import aiohttp
from typing import Dict, List, Set
from web3 import Web3
import asyncio
from decimal import Decimal

logger = logging.getLogger(__name__)

class TokenDiscovery:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self._session = None
        self._lock = asyncio.Lock()
        self.discovered_tokens: Dict[str, Dict] = {}
        self.min_liquidity_usd = 100000  # Minimum liquidity in USD
        self.min_volume_usd = 50000  # Minimum 24h volume in USD

    async def _ensure_session(self):
        """Ensure aiohttp session exists"""
        async with self._lock:
            if self._session is None:
                self._session = aiohttp.ClientSession()

    async def close(self):
        """Close aiohttp session"""
        if self._session:
            await self._session.close()
            self._session = None

    async def get_top_tokens(self) -> Dict[str, Dict]:
        """Fetch top tokens by market cap and volume from CoinGecko"""
        try:
            await self._ensure_session()
            
            async with self._session.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": "250",
                    "sparkline": "false",
                    "locale": "en"
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    filtered_tokens = {}
                    
                    for token in data:
                        # Skip if token doesn't meet minimum requirements
                        if (token.get('total_volume', 0) < self.min_volume_usd or
                            not token.get('platforms', None)):
                            continue
                            
                        token_data = {
                            'id': token['id'],
                            'symbol': token['symbol'].upper(),
                            'name': token['name'],
                            'market_cap': token['market_cap'],
                            'volume_24h': token['total_volume'],
                            'price_usd': token['current_price'],
                            'platforms': {}  # Will be populated with contract addresses
                        }
                        filtered_tokens[token['id']] = token_data
                        
                    return filtered_tokens
                else:
                    logger.error(f"Failed to fetch top tokens: {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching top tokens: {str(e)}")
            return {}

    async def get_token_contracts(self, token_id: str) -> Dict[str, str]:
        """Fetch token contract addresses for different platforms"""
        try:
            await self._ensure_session()
            
            async with self._session.get(
                f"https://api.coingecko.com/api/v3/coins/{token_id}",
                params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('platforms', {})
                else:
                    logger.error(f"Failed to fetch token contracts: {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error fetching token contracts: {str(e)}")
            return {}

    async def get_dex_pairs(self, token_address: str) -> List[Dict]:
        """Fetch trading pairs for a token from DEXes"""
        try:
            await self._ensure_session()
            
            # Query both Uniswap and Sushiswap for pairs
            pairs = []
            
            # Example query for Uniswap V2 (you would need the subgraph URLs)
            uniswap_query = """
            {
                pairs(where: {
                    or: [
                        { token0: "%s" },
                        { token1: "%s" }
                    ]
                }, orderBy: reserveUSD, orderDirection: desc, first: 10) {
                    id
                    token0 { id, symbol }
                    token1 { id, symbol }
                    reserveUSD
                    volumeUSD
                }
            }
            """ % (token_address.lower(), token_address.lower())
            
            # Fetch Uniswap pairs
            async with self._session.post(
                "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2",
                json={"query": uniswap_query}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    for pair in data.get('data', {}).get('pairs', []):
                        if float(pair['reserveUSD']) >= self.min_liquidity_usd:
                            pairs.append({
                                'dex': 'uniswap',
                                'pair_address': pair['id'],
                                'token0': pair['token0'],
                                'token1': pair['token1'],
                                'liquidity_usd': float(pair['reserveUSD']),
                                'volume_usd': float(pair['volumeUSD'])
                            })
            
            return pairs
            
        except Exception as e:
            logger.error(f"Error fetching DEX pairs: {str(e)}")
            return []

    async def discover_tokens(self) -> Dict[str, Dict]:
        """Main method to discover and filter viable tokens for arbitrage"""
        try:
            # Get top tokens by market cap and volume
            top_tokens = await self.get_top_tokens()
            viable_tokens = {}
            
            for token_id, token_data in top_tokens.items():
                # Get contract addresses for each platform
                contracts = await self.get_token_contracts(token_id)
                
                # Skip if no Ethereum contract
                if 'ethereum' not in contracts:
                    continue
                    
                ethereum_address = contracts['ethereum']
                
                # Verify contract address
                if not self.w3.is_address(ethereum_address):
                    continue
                    
                # Get DEX pairs
                pairs = await self.get_dex_pairs(ethereum_address)
                
                # Only include tokens with sufficient DEX presence
                if pairs:
                    token_data['address'] = ethereum_address
                    token_data['pairs'] = pairs
                    viable_tokens[token_id] = token_data
                    
                    logger.info(f"Discovered viable token: {token_data['symbol']} ({token_data['name']})")
                    logger.info(f"DEX pairs found: {len(pairs)}")
                    
                # Add small delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            self.discovered_tokens = viable_tokens
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
            new_tokens = await self.discover_tokens()
            self.discovered_tokens = new_tokens
            logger.info(f"Updated {len(new_tokens)} tokens' data")
        except Exception as e:
            logger.error(f"Error updating token data: {str(e)}")