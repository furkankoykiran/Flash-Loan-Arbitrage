import logging
import aiohttp
from typing import Dict, Any
from datetime import datetime
from decimal import Decimal
import asyncio
import tracemalloc

# Enable tracemalloc to track memory allocations
tracemalloc.start()

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, bot_token: str, channel_id: str):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else ""
        self._session = None
        self._lock = asyncio.Lock()

    def is_enabled(self) -> bool:
        """Check if the notifier is properly configured"""
        return bool(self.bot_token and self.channel_id and 
                   self.bot_token != "your_telegram_bot_token" and 
                   self.channel_id != "your_telegram_chat_id")

    async def _ensure_session(self):
        """Ensure aiohttp session exists with lock protection"""
        if not self.is_enabled():
            return False
            
        async with self._lock:
            if self._session is None:
                self._session = aiohttp.ClientSession()
        return True

    async def close(self):
        """Close aiohttp session"""
        if self._session:
            await self._session.close()
            self._session = None

    def format_value(self, value: Any) -> str:
        """Format values for display, handling Decimal types"""
        if isinstance(value, Decimal):
            return f"{float(value):.6f}"
        return str(value)

    async def send_message(self, text: str) -> bool:
        """Send message to Telegram channel"""
        if not self.is_enabled():
            return False

        try:
            if not await self._ensure_session():
                return False
            
            async with self._lock:
                url = f"{self.base_url}/sendMessage"
                data = {
                    "chat_id": self.channel_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                
                async with self._session.post(url, json=data) as response:
                    if response.status == 200:
                        logger.debug("Telegram notification sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logger.debug(f"Failed to send Telegram message: {response.status}, {error_text}")
                        return False
                    
        except Exception as e:
            logger.debug(f"Failed to send Telegram message: {str(e)}")
            return False

    async def send_arbitrage_opportunity(self, data: Dict[str, Any]) -> None:
        """Send arbitrage opportunity details"""
        if not self.is_enabled():
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        template = (
            f"💡 <b>Arbitrage Opportunity Detected</b>\n"
            f"⏰ {timestamp}\n\n"
            
            f"📊 <b>Trade Details:</b>\n"
            f"• Route: {data['route']}\n"
            f"• Input: {data['input_amount_formatted']}\n"
            f"• Expected Output: {data['output_amount_formatted']}\n\n"
            
            f"💰 <b>Profit Analysis:</b>\n"
            f"• Gross Profit: {data['gross_profit_formatted']}\n"
            f"• Gas Cost: {self.format_value(data['gas_cost_eth'])} ETH (${data['gas_cost_usd']})\n"
            f"• DEX Fees: ${data.get('dex_fees_usd', '0.00')}\n"
            f"• Net Profit: {data['net_profit_formatted']}\n"
            f"• ROI: {data['roi']}%\n\n"
            
            f"📈 <b>Market Conditions:</b>\n"
            f"• ETH Price: ${data['eth_price']}\n"
            f"• Gas Price: {data['gas_price']} gwei\n"
            f"• Block: {data['block_number']}\n\n"
            
            f"👛 <b>Wallet Status:</b>\n"
            f"• ETH Balance: {self.format_value(data['eth_balance'])} ETH\n"
        )
        
        for token, balance in data['token_balances'].items():
            template += f"• {token}: {self.format_value(balance)}\n"
        
        await self.send_message(template)

    async def send_execution_result(self, success: bool, data: Dict[str, Any]) -> None:
        """Send arbitrage execution result"""
        if not self.is_enabled():
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if success:
            template = (
                f"✅ <b>Arbitrage Trade Successful</b>\n"
                f"⏰ {timestamp}\n\n"
                
                f"💰 <b>Trade Summary:</b>\n"
                f"• Token: {data['token_symbol']}\n"
                f"• Profit: {self.format_value(data['profit_token'])} ({data['token_symbol']})\n"
                f"• USD Value: ${self.format_value(data['profit_usd'])}\n"
                f"• ROI: {self.format_value(data['roi'])}%\n"
            )
        else:
            template = (
                f"❌ <b>Arbitrage Trade Failed</b>\n"
                f"⏰ {timestamp}\n\n"
                f"⚠️ Error: {data.get('error', 'Unknown error')}\n"
            )
        
        await self.send_message(template)

    async def send_status_update(self, data: Dict[str, Any]) -> None:
        """Send periodic status update"""
        if not self.is_enabled():
            return

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            template = (
                f"📊 <b>Bot Status Update</b>\n"
                f"⏰ {timestamp}\n\n"
                
                f"📈 <b>Market Conditions:</b>\n"
                f"• ETH Price: ${data['eth_price']}\n"
                f"• Gas Price: {data['gas_price']} gwei\n"
                f"• Block: {data['block_number']}\n\n"
                
                f"👛 <b>Wallet Status:</b>\n"
                f"• ETH Balance: {self.format_value(data['eth_balance'])} ETH\n"
            )
            
            for token, balance in data['token_balances'].items():
                template += f"• {token}: {self.format_value(balance)}\n"
            
            template += (
                f"\n🤖 <b>Bot Statistics:</b>\n"
                f"• Opportunities Found: {data['opportunities_found']}\n"
                f"• Successful Trades: {data['successful_trades']}\n"
                f"• Failed Trades: {data['failed_trades']}\n"
                f"• Total Profit: {self.format_value(data.get('total_profit_eth', Decimal('0.0')))} ETH "
                f"(${self.format_value(data.get('total_profit_usd', Decimal('0.0')))})\n"
                f"• Running Since: {data['start_time']}\n"
                f"• Runtime: {data['runtime_hours']} hours"
            )
            
            await self.send_message(template)
        except Exception as e:
            logger.debug(f"Error sending status update: {str(e)}")

    async def notify_error(self, error: str) -> None:
        """Send error notification"""
        if not self.is_enabled():
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        template = (
            f"🚨 <b>Error Alert</b>\n"
            f"⏰ {timestamp}\n\n"
            f"Error: {error}"
        )
        
        await self.send_message(template)