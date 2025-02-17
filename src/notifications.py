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
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
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

    async def send_message(self, text: str) -> bool:
        """Send message to Telegram channel"""
        try:
            await self._ensure_session()
            
            async with self._lock:
                url = f"{self.base_url}/sendMessage"
                data = {
                    "chat_id": self.channel_id,
                    "text": text,
                    "parse_mode": "HTML"
                }
                
                async with self._session.post(url, json=data) as response:
                    if response.status == 200:
                        logger.info("Telegram notification sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to send Telegram message: {response.status}, {error_text}")
                        return False
                    
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False

    async def format_and_send(self, template: str, data: Dict[str, Any]) -> bool:
        """Format message template and send"""
        try:
            message = template.format(**data)
            return await self.send_message(message)
        except Exception as e:
            logger.error(f"Error formatting message: {str(e)}")
            return False

    async def send_arbitrage_opportunity(self, data: Dict[str, Any]) -> None:
        """Send arbitrage opportunity details"""
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
            f"• Gas Cost: {data['gas_cost_eth']} ETH (${data['gas_cost_usd']})\n"
            f"• DEX Fees: ${data.get('dex_fees_usd', '0.00')}\n"
            f"• Net Profit: {data['net_profit_formatted']}\n"
            f"• ROI: {data['roi']}%\n\n"
            
            f"📈 <b>Market Conditions:</b>\n"
            f"• ETH Price: ${data['eth_price']}\n"
            f"• Gas Price: {data['gas_price']} gwei\n"
            f"• Block: {data['block_number']}\n\n"
            
            f"👛 <b>Wallet Status:</b>\n"
            f"• ETH Balance: {data['eth_balance']} ETH\n"
        )
        
        for token, balance in data['token_balances'].items():
            template += f"• {token}: {balance}\n"
        
        await self.send_message(template)

    async def send_execution_result(self, success: bool, data: Dict[str, Any]) -> None:
        """Send arbitrage execution result"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if success:
            template = (
                f"✅ <b>Arbitrage Trade Successful</b>\n"
                f"⏰ {timestamp}\n\n"
                
                f"💰 <b>Trade Summary:</b>\n"
                f"• Token: {data['token_symbol']}\n"
                f"• Profit: {data['profit_token']:.6f} ({data['token_symbol']})\n"
                f"• USD Value: ${data['profit_usd']:.2f}\n"
                f"• ROI: {data['roi']:.2f}%\n"
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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        template = (
            f"📊 <b>Bot Status Update</b>\n"
            f"⏰ {timestamp}\n\n"
            
            f"📈 <b>Market Conditions:</b>\n"
            f"• ETH Price: ${data['eth_price']}\n"
            f"• Gas Price: {data['gas_price']} gwei\n"
            f"• Block: {data['block_number']}\n\n"
            
            f"👛 <b>Wallet Status:</b>\n"
            f"• ETH Balance: {data['eth_balance']} ETH\n"
        )
        
        for token, balance in data['token_balances'].items():
            template += f"• {token}: {balance}\n"
        
        template += (
            f"\n🤖 <b>Bot Statistics:</b>\n"
            f"• Opportunities Found: {data['opportunities_found']}\n"
            f"• Successful Trades: {data['successful_trades']}\n"
            f"• Failed Trades: {data['failed_trades']}\n"
            f"• Total Profit: {data['total_profit']} ETH\n"
            f"• Running Since: {data['start_time']}\n"
            f"• Runtime: {data['runtime_hours']} hours"
        )
        
        await self.send_message(template)

    async def notify_error(self, error: str) -> None:
        """Send error notification"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        template = (
            f"🚨 <b>Error Alert</b>\n"
            f"⏰ {timestamp}\n\n"
            f"Error: {error}"
        )
        
        await self.send_message(template)