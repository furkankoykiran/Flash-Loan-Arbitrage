import sys
import logging
import asyncio
from decimal import Decimal
import argparse
from web3 import Web3
import signal

from .config import Config
from .arbitrage_bot import ArbitrageBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class GracefulExit:
    """Handle graceful exit on Ctrl+C"""
    def __init__(self, bot=None):
        self.shutdown = False
        self.bot = bot
        signal.signal(signal.SIGINT, self._exit_gracefully)
        signal.signal(signal.SIGTERM, self._exit_gracefully)

    def _exit_gracefully(self, signum, frame):
        logger.info("\n👋 Received shutdown signal, stopping bot...")
        self.shutdown = True
        if self.bot:
            asyncio.create_task(self.bot.stop())

async def cleanup(config: Config):
    """Clean up resources"""
    try:
        if config:
            await config.close()
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

async def run_arbitrage_bot():
    """Main bot execution function"""
    parser = argparse.ArgumentParser(description='Flash Loan Arbitrage Bot')
    parser.add_argument(
        '--min-profit',
        type=float,
        help='Minimum profit threshold in ETH (overrides .env setting)',
        default=0.0001
    )
    
    args = parser.parse_args()
    config = None
    bot = None

    try:
        # Initialize configuration
        config = Config()
        
        # Override minimum profit threshold if specified
        if args.min_profit is not None:
            config.min_profit_threshold = Decimal(str(args.min_profit))

        # Validate environment
        if not config.validate_config():
            logger.error("""
Missing required configuration. Please check your .env file and ensure all required values are set:
- NETWORK_RPC_URL (should be WebSocket URL starting with ws://)
- PRIVATE_KEY
- WALLET_ADDRESS
            """)
            return

        # Initialize arbitrage bot
        bot = ArbitrageBot(config)
        await bot.initialize()
        
        # Set up exit handler with bot instance
        exit_handler = GracefulExit(bot)
        
        # Run monitoring loop
        try:
            await bot.monitor_opportunities()
        except KeyboardInterrupt:
            logger.info("\n👋 Stopping arbitrage bot...")
            await bot.stop()
        except Exception as e:
            logger.error(f"Error in monitoring loop: {str(e)}")
            if bot:
                await bot.stop()

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
    finally:
        # Ensure cleanup is performed
        try:
            if bot:
                await bot.stop()
            elif config:
                await cleanup(config)
            logger.info("Cleanup completed")
        except Exception as e:
            logger.error(f"Error during final cleanup: {str(e)}")

def main():
    """Entry point with proper asyncio handling"""
    try:
        if sys.platform == 'win32':
            # Set up proper event loop policy for Windows
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
        # Create and get event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run the bot
            loop.run_until_complete(run_arbitrage_bot())
        finally:
            # Clean up the loop
            try:
                # Cancel all running tasks
                tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
                if tasks:
                    for task in tasks:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            finally:
                loop.close()
                
    except KeyboardInterrupt:
        logger.info("\n👋 Stopping arbitrage bot...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()