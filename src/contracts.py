from typing import Dict, List, Optional, Callable, Any
from web3 import Web3
from web3.contract import Contract
import asyncio
import json
import logging
from eth_account.messages import encode_defunct

logger = logging.getLogger(__name__)

class ContractInterface:
    # Trading pairs configuration remains the same
    TRADING_PAIRS = {
        'WETH-USDT': {
            'tokens': ['WETH', 'USDT'],
            'addresses': {
                'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
                'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7'
            }
        },
        'WETH-USDC': {
            'tokens': ['WETH', 'USDC'],
            'addresses': {
                'WETH': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
                'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
            }
        },
        'WBTC-USDT': {
            'tokens': ['WBTC', 'USDT'],
            'addresses': {
                'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
                'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7'
            }
        },
        'WBTC-USDC': {
            'tokens': ['WBTC', 'USDC'],
            'addresses': {
                'WBTC': '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
                'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
            }
        },
        'DAI-USDT': {
            'tokens': ['DAI', 'USDT'],
            'addresses': {
                'DAI': '0x6B175474E89094C44Da98b954EedeAC495271d0F',
                'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7'
            }
        },
        'DAI-USDC': {
            'tokens': ['DAI', 'USDC'],
            'addresses': {
                'DAI': '0x6B175474E89094C44Da98b954EedeAC495271d0F',
                'USDC': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
            }
        }
    }

    # ABIs remain the same
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
        
    def get_dex_router(self, address: str) -> Contract:
        """Get DEX router contract"""
        key = f'router_{address.lower()}'
        if key not in self._contracts:
            self._contracts[key] = self.w3.eth.contract(
                address=self.w3.to_checksum_address(address),
                abi=self.DEX_ROUTER_ABI
            )
        return self._contracts[key]

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

    async def get_token_allowance(self, token_contract: Contract, owner: str, spender: str) -> int:
        """Get token allowance asynchronously"""
        allowance = token_contract.functions.allowance(owner, spender).call()
        return allowance

    async def check_and_approve_token(
        self,
        token_address: str,
        spender_address: str,
        owner_address: str,
        private_key: str
    ) -> bool:
        """Check allowance and approve if needed"""
        try:
            token = self.get_token_contract(token_address)
            
            # Check current allowance
            allowance = await self.get_token_allowance(token, owner_address, spender_address)
            
            if allowance > 0:
                logger.info(f"Token {token_address} already approved for {spender_address}")
                return True
            
            logger.info(f"Approving token {token_address} for {spender_address}...")
            
            # Build approval transaction
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
            
            # Sign and send transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] == 1:
                logger.info(f"Successfully approved token {token_address} for {spender_address}")
                return True
            else:
                logger.error(f"Approval transaction failed for token {token_address}")
                return False
                
        except Exception as e:
            logger.error(f"Token approval failed: {str(e)}")
            return False

    async def execute_trades(
        self,
        amount: int,
        path1: List[str],
        path2: List[str],
        wallet_address: str,
        private_key: str
    ) -> bool:
        """Execute trades on both DEXes"""
        try:
            # Get current block for deadline
            block = self.w3.eth.get_block('latest')
            deadline = block['timestamp'] + 300  # 5 minutes
            
            # Execute first trade (Uniswap)
            logger.info("Executing first trade on Uniswap...")
            tx_hash1 = await self._execute_swap(
                self.get_dex_router(self.config.uniswap_router),
                amount,
                path1,
                wallet_address,
                deadline,
                private_key
            )
            
            if not tx_hash1:
                return False
                
            # Get new balance for second trade
            token_contract = self.get_token_contract(path1[-1])
            new_balance = await self.get_token_balance(token_contract, wallet_address)
            
            # Execute second trade (Sushiswap)
            logger.info("Executing second trade on Sushiswap...")
            tx_hash2 = await self._execute_swap(
                self.get_dex_router(self.config.sushiswap_router),
                new_balance,
                path2,
                wallet_address,
                deadline,
                private_key
            )
            
            return bool(tx_hash2)
            
        except Exception as e:
            logger.error(f"Error executing trades: {str(e)}")
            return False

    async def _execute_swap(
        self,
        router: Contract,
        amount_in: int,
        path: List[str],
        wallet_address: str,
        deadline: int,
        private_key: str
    ) -> Optional[str]:
        """Execute a swap on a DEX"""
        try:
            # Get nonce
            nonce = self.w3.eth.get_transaction_count(wallet_address)
            
            # Get gas price
            gas_price = self.w3.eth.gas_price
            
            # Build swap transaction
            swap_tx = router.functions.swapExactTokensForTokens(
                amount_in,
                0,  # Accept any amount of tokens
                path,
                wallet_address,
                deadline
            ).build_transaction({
                'from': wallet_address,
                'gas': 300000,  # Estimated gas limit
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            
            # Sign transaction
            signed_tx = self.w3.eth.account.sign_transaction(swap_tx, private_key)
            
            # Send transaction
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            # Wait for confirmation
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt['status'] == 1:
                logger.info(f"Swap successful: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Swap failed: {tx_hash.hex()}")
                return None
                
        except Exception as e:
            logger.error(f"Error executing swap: {str(e)}")
            return None

    def get_all_pairs(self) -> Dict:
        """Get all trading pairs configuration"""
        return self.TRADING_PAIRS

    async def get_token_info(self, token_address: str) -> Optional[Dict]:
        """Get token decimals and contract"""
        try:
            token = self.get_token_contract(token_address)
            decimals = await self.get_token_decimals(token)
            return {
                'decimals': decimals,
                'contract': token
            }
        except Exception as e:
            logger.error(f"Failed to get token info: {str(e)}")
            return None

    async def initialize_pair_decimals(self):
        """Initialize decimals for all trading pairs"""
        for pair_name, pair_data in self.TRADING_PAIRS.items():
            for token_symbol, token_address in pair_data['addresses'].items():
                if token_address not in self.pair_decimals:
                    token_info = await self.get_token_info(token_address)
                    if token_info:
                        self.pair_decimals[token_address] = token_info['decimals']

    async def setup_websocket(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Setup WebSocket connection for real-time updates"""
        try:
            self._ws_subscription = await self.w3.eth.subscribe('newHeads')
            self._ws_subscription.subscribe(callback)
            logger.info("WebSocket connection established")
            return True
        except Exception as e:
            logger.error(f"WebSocket setup failed: {str(e)}")
            return False