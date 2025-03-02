from typing import Dict, List, Optional, Callable, Any, Tuple
from web3 import Web3
from web3.contract import Contract
import asyncio
import json
import logging
from eth_account.messages import encode_defunct

logger = logging.getLogger(__name__)

class ContractInterface:
    # Common token addresses
    TOKENS = {
        'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
        'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
        'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
        'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
        'DAI': '0x6B175474E89094C44Da98b954EedeAC495271d0F',
    }

    # DEX Registry with verification status
    DEX_REGISTRY = {
        'uniswap_v2': {
            'router': '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
            'name': 'Uniswap V2',
            'fee': 0.003,  # 0.3%
            'verified': True
        },
        'sushiswap': {
            'router': '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F',
            'name': 'SushiSwap',
            'fee': 0.003,  # 0.3%
            'verified': True
        },
        'uniswap_v3': {
            'router': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
            'name': 'Uniswap V3',
            'fee': 0.003,  # Variable, using default
            'verified': True
        },
        'pancakeswap': {
            'router': '0x10ED43C718714eb63d5aA57B78B54704E256024E',
            'name': 'PancakeSwap',
            'fee': 0.0025,  # 0.25%
            'verified': True
        },
    }

    # Extended Router ABI to support various DEX features
    DEX_ROUTER_ABI = [
        {
            "inputs": [
                {"name": "amountIn", "type": "uint256"},
                {"name": "path", "type": "address[]"}
            ],
            "name": "getAmountsOut",
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactTokensForTokens",
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [
                {"name": "tokenA", "type": "address"},
                {"name": "tokenB", "type": "address"}
            ],
            "name": "getReserves",
            "outputs": [
                {"name": "reserveA", "type": "uint112"},
                {"name": "reserveB", "type": "uint112"},
                {"name": "blockTimestampLast", "type": "uint32"}
            ],
            "stateMutability": "view",
            "type": "function"
        }
    ]

    ERC20_ABI = [
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [
                {"name": "_spender", "type": "address"},
                {"name": "_value", "type": "uint256"}
            ],
            "name": "approve",
            "outputs": [{"name": "", "type": "bool"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [
                {"name": "_owner", "type": "address"},
                {"name": "_spender", "type": "address"}
            ],
            "name": "allowance",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        }
    ]

    def __init__(self, w3: Web3, config=None):
        self.w3 = w3
        self.config = config
        self._contracts: Dict[str, Contract] = {}
        self._ws_subscription = None
        self.pair_decimals = {}
        self.dex_routers = {}

    def get_supported_dexes(self) -> List[str]:
        """Get list of supported DEX identifiers"""
        return list(self.DEX_REGISTRY.keys())

    def get_dex_info(self, dex_id: str) -> Optional[Dict]:
        """Get DEX information by ID"""
        return self.DEX_REGISTRY.get(dex_id)

    def get_dex_router(self, dex_id: str) -> Optional[Contract]:
        """Get DEX router contract by ID"""
        if dex_id in self.dex_routers:
            return self.dex_routers[dex_id]

        dex_info = self.get_dex_info(dex_id)
        if not dex_info:
            return None

        router = self.w3.eth.contract(
            address=self.w3.to_checksum_address(dex_info['router']),
            abi=self.DEX_ROUTER_ABI
        )
        self.dex_routers[dex_id] = router
        return router

    def get_token_contract(self, address: str) -> Contract:
        """Get token contract"""
        key = f'token_{address.lower()}'
        if key not in self._contracts:
            self._contracts[key] = self.w3.eth.contract(
                address=self.w3.to_checksum_address(address),
                abi=self.ERC20_ABI
            )
        return self._contracts[key]

    async def get_token_balance(self, token_contract: Contract, wallet_address: str) -> int:
        """Get token balance asynchronously"""
        balance = token_contract.functions.balanceOf(wallet_address).call()
        return balance

    async def get_token_decimals(self, token_contract: Contract) -> int:
        """Get token decimals asynchronously"""
        decimals = token_contract.functions.decimals().call()
        return decimals

    async def check_and_approve_token(
        self,
        token_address: str,
        dex_ids: List[str],
        owner_address: str,
        private_key: str
    ) -> bool:
        """Check allowance and approve for multiple DEXes"""
        try:
            token = self.get_token_contract(token_address)
            success = True

            for dex_id in dex_ids:
                dex_info = self.get_dex_info(dex_id)
                if not dex_info:
                    continue

                spender_address = dex_info['router']
                allowance = await self.get_token_allowance(token, owner_address, spender_address)

                if allowance == 0:
                    logger.info(f"Approving {token_address} for {dex_id}...")
                    
                    nonce = self.w3.eth.get_transaction_count(owner_address)
                    gas_price = self.w3.eth.gas_price

                    tx = token.functions.approve(
                        spender_address,
                        2**256 - 1  # Max approval
                    ).build_transaction({
                        'from': owner_address,
                        'gas': 100000,
                        'gasPrice': gas_price,
                        'nonce': nonce,
                    })

                    signed_tx = self.w3.eth.account.sign_transaction(tx, private_key)
                    tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

                    if receipt['status'] != 1:
                        logger.error(f"Approval failed for {dex_id}")
                        success = False

            return success

        except Exception as e:
            logger.error(f"Token approval failed: {str(e)}")
            return False

    async def get_token_allowance(self, token_contract: Contract, owner: str, spender: str) -> int:
        """Get token allowance asynchronously"""
        allowance = token_contract.functions.allowance(owner, spender).call()
        return allowance

    async def execute_trade(
        self,
        dex_id: str,
        amount: int,
        path: List[str],
        wallet_address: str,
        deadline: int,
        private_key: str
    ) -> Optional[str]:
        """Execute a trade on a specific DEX"""
        try:
            router = self.get_dex_router(dex_id)
            if not router:
                raise ValueError(f"DEX {dex_id} not found")

            nonce = self.w3.eth.get_transaction_count(wallet_address)
            gas_price = self.w3.eth.gas_price

            # Build swap transaction
            swap_tx = router.functions.swapExactTokensForTokens(
                amount,
                0,  # Accept any amount of tokens
                path,
                wallet_address,
                deadline
            ).build_transaction({
                'from': wallet_address,
                'gas': 300000,
                'gasPrice': gas_price,
                'nonce': nonce,
            })

            # Sign and send transaction
            signed_tx = self.w3.eth.account.sign_transaction(swap_tx, private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            if receipt['status'] == 1:
                logger.info(f"Trade successful on {dex_id}: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Trade failed on {dex_id}: {tx_hash.hex()}")
                return None

        except Exception as e:
            logger.error(f"Error executing trade on {dex_id}: {str(e)}")
            return None

    async def get_price_quote(
        self,
        dex_id: str,
        amount_in: int,
        path: List[str]
    ) -> Optional[List[int]]:
        """Get price quote from a specific DEX"""
        try:
            router = self.get_dex_router(dex_id)
            if not router:
                return None

            amounts = router.functions.getAmountsOut(amount_in, path).call()
            return amounts
        except Exception as e:
            logger.error(f"Error getting price quote from {dex_id}: {str(e)}")
            return None

    async def get_dex_reserves(
        self,
        dex_id: str,
        token_a: str,
        token_b: str
    ) -> Optional[Tuple[int, int]]:
        """Get pair reserves from a specific DEX"""
        try:
            router = self.get_dex_router(dex_id)
            if not router:
                return None

            reserves = router.functions.getReserves(token_a, token_b).call()
            return (reserves[0], reserves[1])
        except Exception as e:
            logger.debug(f"Error getting reserves from {dex_id}: {str(e)}")
            return None

    async def verify_dex_security(self, dex_id: str) -> bool:
        """Verify DEX security status"""
        dex_info = self.get_dex_info(dex_id)
        if not dex_info:
            return False
        return dex_info.get('verified', False)

    def add_dex(
        self,
        dex_id: str,
        router_address: str,
        name: str,
        fee: float,
        verified: bool = False
    ) -> bool:
        """Add a new DEX to the registry"""
        try:
            self.DEX_REGISTRY[dex_id] = {
                'router': router_address,
                'name': name,
                'fee': fee,
                'verified': verified
            }
            return True
        except Exception as e:
            logger.error(f"Error adding DEX {dex_id}: {str(e)}")
            return False