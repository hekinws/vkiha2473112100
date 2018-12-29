#!/usr/bin/env python3
# coding=utf-8

import os
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

import asyncio
import logging
from textwrap import shorten

try:
    import aiohttp
except ModuleNotFoundError:
    import sys
    import subprocess
    print("=== Установка зависимостей ===")
    pip_command = [sys.executable, "-m", "pip", "install", "--no-deps",
                   "-r", SCRIPT_DIR + "/requirements.txt"]
    if sys.version_info.minor < 7:  # there's no idna-ssl for python 3.7
        pip_command.append("idna-ssl==1.0.1")
    subprocess.check_call(pip_command)
    import aiohttp

import aiohttp.client_exceptions

import aiovk
import aiovk.exceptions
from aiovk.drivers import HttpDriver
from aiovk.mixins import LimitRateDriverMixin

from vk_api.longpoll import Event, VkEventType, VkMessageFlag

logging.basicConfig(format="%(asctime)s| %(levelname)s: %(message)s",
                    datefmt="%H:%M:%S", level=logging.INFO)

with open(SCRIPT_DIR + "/README.txt") as readme:
    print(readme.read())


class LimitRateDriver(LimitRateDriverMixin, HttpDriver):
    requests_per_period = 3


class Account:
    def __init__(self, token: str):
        self._token = token
        self.short_token = self._token[:5]

        self.loop = asyncio.get_event_loop()
        self._session = self.loop.run_until_complete(self._create_session())

        self.api = aiovk.API(self._session)
        self.longpoll = aiovk.LongPoll(self.api, wait=25, mode=0, version=1)

    async def _create_session(self):
        connector = aiohttp.TCPConnector(verify_ssl=False)
        session = aiohttp.ClientSession(connector=connector)
        driver = LimitRateDriver(loop=self.loop, session=session)
        return aiovk.TokenSession(access_token=self._token, driver=driver)

    def is_income_message(self, event: Event) -> bool:
        """Checks whether event is new income not important message"""
        return (event.type == VkEventType.MESSAGE_NEW and
                event.to_me and
                VkMessageFlag.IMPORTANT not in event.message_flags)

    async def listen_income_messages(self) -> Event:
        while True:
            try:
                raw_events = await self.longpoll.wait()
            except asyncio.TimeoutError:
                logging.critical("тайм-аут: что-то с интернетом")
            except (aiovk.exceptions.VkException,
                    aiohttp.client_exceptions.ClientError) as err:
                name = type(err).__name__
                logging.error("%s:ошибка %s: %s", self.short_token, name, err)
            else:
                logging.debug("%s:получено %s", self.short_token, raw_events)
                messages = (Event(raw) for raw in raw_events["updates"]
                                       if raw[0] == VkEventType.MESSAGE_NEW)
                income = filter(self.is_income_message, messages)
                for message in income:
                    yield message

    async def mark_messages_important(self):
        async for message in self.listen_income_messages():  # type: Event
            try:
                id = message.message_id
                await self.api.messages.markAsImportant(message_ids=id,
                                                        important=1)
            except asyncio.TimeoutError:
                logging.critical("тайм-аут: что-то с интернетом")
            except (aiovk.exceptions.VkException,
                    aiohttp.client_exceptions.ClientError) as err:
                name = type(err).__name__
                logging.error("%s:ошибка %s: %s", self.short_token, name, err)
            else:
                text = shorten(message.text, width=25)
                if text == "[...]":  # for very long single words
                    text = message.text[:20] + "[...]"
                logging.info("%s:обработано: %s", self.short_token, text)


tokens_filename = SCRIPT_DIR + "/tokens.txt"
open(tokens_filename, 'a').close()  # create file if not exists

with open(tokens_filename) as tokens_file:
    tokens = [token.strip() for token in tokens_file if token.strip()]

for token in tokens:
    account = Account(token)
    asyncio.ensure_future(account.mark_messages_important())
    logging.info("%s:аккаунт добавлен", account.short_token)

logging.getLogger("asyncio").setLevel(logging.WARNING)
loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
loop.run_forever()
