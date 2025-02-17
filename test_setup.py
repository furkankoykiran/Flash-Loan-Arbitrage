import logging
from decimal import Decimal
from src.config import Config
from src.market_utils import MarketUtils
from web3 import Web3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_configuration():
    """Test the bot configuration and connections"""
    try:
        # Initialize configuration
        config = Config()
        logger.info("✅ Configuration loaded successfully")
        
        # Test network connection
        if not config.is_connected():
            logger.error("❌ Cannot connect to Ethereum network")
            return False
        logger.info(f"✅ Connected to Ethereum network (Chain ID: {config.chain_id})")
        
        # Test wallet
        try:
            balance = config.w3.eth.get_balance(config.wallet_address)
            eth_balance = Web3.from_wei(balance, 'ether')
            logger.info(f"✅ Wallet connected - Balance: {eth_balance:.6f} ETH")
        except Exception as e:
            logger.error(f"❌ Wallet error: {str(e)}")
            return False
        
        # Test token contracts
        for symbol, address in config.token_addresses.items():
            try:
                contract = config.w3.eth.contract(
                    address=Web3.to_checksum_address(address),
                    abi=[{
                        "constant": True,
                        "inputs": [],
                        "name": "decimals",
                        "outputs": [{"name": "", "type": "uint8"}],
                        "type": "function"
                    }]
                )
                decimals = contract.functions.decimals().call()
                logger.info(f"✅ {symbol} contract connected - Decimals: {decimals}")
            except Exception as e:
                logger.error(f"❌ Error connecting to {symbol} contract: {str(e)}")
                return False
        
        # Test DEX routers
        routers = {
            'Uniswap': config.uniswap_router,
            'Sushiswap': config.sushiswap_router
        }
        
        for dex, address in routers.items():
            try:
                Web3.to_checksum_address(address)
                logger.info(f"✅ {dex} router address verified")
            except Exception as e:
                logger.error(f"❌ Invalid {dex} router address: {str(e)}")
                return False
        
        # Test market utils
        try:
            eth_price = config.market_utils.get_eth_price()
            logger.info(f"✅ Market price feed working - ETH: ${eth_price:.2f}")
        except Exception as e:
            logger.error(f"❌ Error fetching market prices: {str(e)}")
            return False
        
        # Test gas price
        try:
            gas_price = Web3.from_wei(config.get_gas_price(), 'gwei')
            logger.info(f"✅ Gas price: {gas_price:.1f} gwei")
        except Exception as e:
            logger.error(f"❌ Error fetching gas price: {str(e)}")
            return False
        
        # Test Telegram notifications
        if config.notifier:
            try:
                test_message = (
                    "🤖 Arbitrage Bot Test Message\n\n"
                    f"• ETH Balance: {eth_balance:.6f}\n"
                    f"• Gas Price: {gas_price:.1f} gwei\n"
                    f"• ETH Price: ${eth_price:.2f}"
                )
                if config.notifier.send_message(test_message):
                    logger.info("✅ Telegram notifications working")
                else:
                    logger.warning("⚠️ Failed to send Telegram message")
            except Exception as e:
                logger.error(f"❌ Telegram error: {str(e)}")
                return False
        else:
            logger.info("ℹ️ Telegram notifications not configured")
        
        logger.info("\n✨ All systems ready!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Configuration test failed: {str(e)}")
        return False

if __name__ == "__main__":
    print("\n🔍 Testing Arbitrage Bot Configuration\n")
    success = test_configuration()
    
    if success:
        print("\n✅ Configuration test passed! You can now run the bot:")
        print("poetry run python -m src.main --check-balance    # Check current balances")
        print("poetry run python -m src.main                    # Check for opportunities")
        print("poetry run python -m src.main --monitor          # Monitor continuously")
    else:
        print("\n❌ Configuration test failed. Please check the errors above and verify your .env file.")