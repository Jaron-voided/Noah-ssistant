import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config

log = logging.getLogger(__name__)


def auth(func):
    """Drop any update silently if it does not come from the authorized user."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id == config.TELEGRAM_USER_ID:
            return await func(update, context)
        if update.effective_user:
            log.warning("Ignored update from unauthorized user %d", update.effective_user.id)
    return wrapper
